// ui/src/components/tabs/TestInterviewDialog.tsx
// Smoke-test interview dialog.
//
// Phases: setup → ready → interviewing → complete
// Closing mid-interview saves position to localStorage; the ready screen
// offers "Resume from Q{n}" so nothing is lost on accidental dismissal.
// Empty responses trigger a single gentle repeat before moving on.
import { useState, useRef, useCallback, useEffect } from 'react'
import { X, Mic, MicOff, CheckCircle2, Copy, ChevronDown, ChevronUp, Volume2, Pause, Play, Pencil, Check } from 'lucide-react'
import { bcp47 } from '../../utils/holidays'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const webkitSpeechRecognition: any

// George — Warm, Captivating Storyteller — ElevenLabs British male voice
const AVERY_VOICE_ID = 'JBFqnCBsd6RMkjVDRZzb'
const AVERY_HIRES    = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/agents/avery-singh-hires.jpg`
const API_BASE       = '/api/interviews/test'

// Gentle repeats Avery uses when no response is detected
const NO_RESPONSE_PROMPTS = [
  'Apologies — I didn\'t quite catch that. ',
  'Sorry about that — let me try again. ',
  'I\'m not sure I heard you there. ',
]

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('ap_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface ScriptQuestion {
  id: string
  text: string
  follow_up_count: number
  probing_instructions: string
  follow_up_branches: string[]
  evasion_signals: string[]
}

interface ScriptSection {
  title: string
  questions: ScriptQuestion[]
}

interface InterviewScript {
  node_label: string
  study_objectives: string[]
  welcome_message: string
  closing_message: string
  sections: ScriptSection[]
}

interface QAPair { question: string; answer: string }

type Phase = 'loading' | 'setup' | 'ready' | 'interviewing' | 'complete' | 'error'

// ── Word-overlap similarity (speculative prefetch validation) ─────────────────

function wordSimilarity(a: string, b: string): number {
  if (!a || !b) return 0
  const wa = new Set(a.toLowerCase().split(/\s+/).filter(Boolean))
  const wb = new Set(b.toLowerCase().split(/\s+/).filter(Boolean))
  return [...wa].filter(w => wb.has(w)).length / Math.max(wa.size, wb.size, 1)
}

// ── Main dialog ───────────────────────────────────────────────────────────────

interface Props { slug: string; onClose: () => void; locale?: string }

// The slug is not decoration. The script comes from the smoke-test project, but the answers
// the consultant types are this project's, and the elaboration press is what sends them to a
// model - so the press has to say which project it belongs to or it cannot be routed by that
// project's llm_mode.
export default function TestInterviewDialog({ slug, onClose, locale = 'GB' }: Props) {
  const [phase, setPhase]             = useState<Phase>('loading')
  const [script, setScript]           = useState<InterviewScript | null>(null)
  const [errorMsg, setErrorMsg]       = useState('')
  const [isFetching, setIsFetching]   = useState(false)
  const [isPlaying, setIsPlaying]     = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [statusMsg, setStatusMsg]     = useState('')
  const [currentQuestion, setCurrentQ] = useState('')
  const [progress, setProgress]       = useState({ current: 0, total: 0 })
  const [transcript, setTranscript]   = useState<QAPair[]>([])
  const [showTranscript, setShowTx]   = useState(false)
  const [isBriefing, setIsBriefing]   = useState(false)
  const [editingIdx, setEditingIdx]   = useState<number | null>(null)
  const [editText, setEditText]       = useState('')
  const [sendCopy, setSendCopy]       = useState(false)
  const [copyEmail, setCopyEmail]     = useState('')

  // Mic/speaker setup
  const [audioInputs, setAudioInputs]     = useState<MediaDeviceInfo[]>([])
  const [audioOutputs, setAudioOutputs]   = useState<MediaDeviceInfo[]>([])
  const [selectedInput, setSelectedInput]   = useState('')
  const [selectedOutput, setSelectedOutput] = useState('')
  const [micLevel, setMicLevel]     = useState(0)
  const [isMicTesting, setIsMicTesting] = useState(false)

  const transcriptRef      = useRef<QAPair[]>([])
  const progressRef        = useRef(0)
  const micTestRef         = useRef<{ stream: MediaStream; ctx: AudioContext; anim: number } | null>(null)
  const speculativeRef     = useRef<{ controller: AbortController; promise: Promise<string>; forText: string } | null>(null)
  const recogRef           = useRef<{ recognition: any; controller: AbortController | null } | null>(null) // eslint-disable-line @typescript-eslint/no-explicit-any
  const audioRef           = useRef<HTMLAudioElement | null>(null)
  const interviewAbortRef  = useRef<AbortController | null>(null)
  const briefingCtxRef     = useRef<AudioContext | null>(null)

  // Thinking-pause state
  const [isPaused, setIsPaused]             = useState(false)
  const [silenceProgress, setSilenceProgress] = useState(0)
  const isPausedRef          = useRef(false)
  const silenceTimerRef      = useRef<ReturnType<typeof setTimeout> | null>(null)
  const silenceIntervalRef   = useRef<ReturnType<typeof setInterval> | null>(null)
  const resetSilenceTimerRef = useRef<(() => void) | null>(null)

  useEffect(() => { loadScript() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => {
    stopMicTestInternal()
    stopListeningInternal()
    speculativeRef.current?.controller.abort()
    interviewAbortRef.current?.abort()
    audioRef.current?.pause()
    briefingCtxRef.current?.close().catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Data fetching ────────────────────────────────────────────────────────────

  async function loadScript() {
    try {
      const res = await fetch(`${API_BASE}/script`, { headers: authHeaders() })
      if (!res.ok) throw new Error(
        res.status === 404
          ? 'Smoke-test script not found — run discovery_mapping on the smoke-test project first.'
          : `Failed to load script (${res.status})`
      )
      const data: InterviewScript = await res.json()
      const total = data.sections.reduce((n, s) => n + s.questions.length, 0)
      setScript(data)
      setProgress({ current: 0, total })
      await enumerateDevices()
      setPhase('setup')
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Unknown error')
      setPhase('error')
    }
  }

  // ── Device enumeration ───────────────────────────────────────────────────────

  async function enumerateDevices() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach(t => t.stop())
    } catch { /* labels will be empty */ }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      const inputs  = devices.filter(d => d.kind === 'audioinput')
      const outputs = devices.filter(d => d.kind === 'audiooutput')
      setAudioInputs(inputs)
      setAudioOutputs(outputs)
      if (inputs[0])  setSelectedInput(inputs[0].deviceId)
      if (outputs[0]) setSelectedOutput(outputs[0].deviceId)
    } catch { /* ignore */ }
  }

  // ── Mic level test ───────────────────────────────────────────────────────────

  async function startMicTest() {
    stopMicTestInternal()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedInput ? { deviceId: { exact: selectedInput } } : true,
      })
      const ctx      = new AudioContext()
      const src      = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 256
      src.connect(analyser)
      const buf = new Uint8Array(analyser.frequencyBinCount)
      function tick() {
        analyser.getByteFrequencyData(buf)
        setMicLevel(Math.min(1, buf.reduce((a, b) => a + b, 0) / buf.length / 80))
        const id = requestAnimationFrame(tick)
        micTestRef.current = { stream, ctx, anim: id }
      }
      const id = requestAnimationFrame(tick)
      micTestRef.current = { stream, ctx, anim: id }
      setIsMicTesting(true)
    } catch {
      setStatusMsg('Could not access microphone — check browser permissions.')
    }
  }

  function stopMicTestInternal() {
    if (!micTestRef.current) return
    const { stream, ctx, anim } = micTestRef.current
    cancelAnimationFrame(anim)
    stream.getTracks().forEach(t => t.stop())
    ctx.close().catch(() => {})
    micTestRef.current = null
    setMicLevel(0)
    setIsMicTesting(false)
  }

  function toggleMicTest() {
    if (isMicTesting) stopMicTestInternal()
    else startMicTest()
  }

  // ── Speaker test ─────────────────────────────────────────────────────────────

  async function testSpeaker() {
    setIsFetching(true)
    try {
      const res = await fetch(`${API_BASE}/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ text: "Hi there, I'm Avery. Your audio is working perfectly.", voice_id: AVERY_VOICE_ID }),
      })
      if (!res.ok) return
      const url = URL.createObjectURL(await res.blob())
      setIsFetching(false)
      setIsPlaying(true)
      const audio = new Audio(url)
      if (selectedOutput && (audio as any).setSinkId) await (audio as any).setSinkId(selectedOutput).catch(() => {}) // eslint-disable-line @typescript-eslint/no-explicit-any
      await new Promise<void>(resolve => {
        audio.onended = () => { URL.revokeObjectURL(url); resolve() }
        audio.onerror = () => { URL.revokeObjectURL(url); resolve() }
        audio.play().catch(() => resolve())
      })
    } finally { setIsFetching(false); setIsPlaying(false) }
  }

  // ── TTS (abort-aware) ─────────────────────────────────────────────────────────

  async function speakText(text: string): Promise<void> {
    const signal = interviewAbortRef.current?.signal
    if (signal?.aborted) return
    setIsFetching(true)
    try {
      const res = await fetch(`${API_BASE}/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ text, voice_id: AVERY_VOICE_ID }),
        signal,
      })
      if (!res.ok || signal?.aborted) return
      const url = URL.createObjectURL(await res.blob())
      setIsFetching(false)
      if (signal?.aborted) { URL.revokeObjectURL(url); return }
      setIsPlaying(true)
      await new Promise<void>(resolve => {
        const audio = new Audio(url)
        audioRef.current = audio
        if (selectedOutput && (audio as any).setSinkId) (audio as any).setSinkId(selectedOutput).catch(() => {}) // eslint-disable-line @typescript-eslint/no-explicit-any
        audio.onended = () => { URL.revokeObjectURL(url); audioRef.current = null; resolve() }
        audio.onerror = () => { URL.revokeObjectURL(url); audioRef.current = null; resolve() }
        audio.play().catch(() => resolve())
      })
    } catch (e) {
      // AbortError from fetch — expected on close, not an error
      if ((e as Error).name !== 'AbortError') console.warn('speakText error', e)
    } finally {
      setIsFetching(false)
      setIsPlaying(false)
    }
  }

  // ── Elaboration press ────────────────────────────────────────────────────────

  function fetchElaborationPress(
    questionText: string, responseText: string, probingInstructions: string, signal?: AbortSignal,
  ): Promise<string> {
    return fetch(`${API_BASE}/elaboration-press`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ question_text: questionText, response_text: responseText, probing_instructions: probingInstructions, slug }),
      signal,
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => d.press_text as string)
      .catch(() => 'Could you tell me a little more about that?')
  }

  // ── Speech recognition ────────────────────────────────────────────────────────

  function stopListeningInternal() {
    if (!recogRef.current) return
    const { recognition } = recogRef.current
    recogRef.current = null
    try { recognition.stop() } catch { /* already stopped */ }
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null }
    if (silenceIntervalRef.current) { clearInterval(silenceIntervalRef.current); silenceIntervalRef.current = null }
    setSilenceProgress(0)
    setIsPaused(false)
    isPausedRef.current = false
    setIsListening(false)
  }

  function submitAnswer() {
    if (!recogRef.current) return
    const r = recogRef.current.recognition
    recogRef.current = null
    try { r.stop() } catch { /* already stopped */ }
  }

  function handlePause() {
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null }
    if (silenceIntervalRef.current) { clearInterval(silenceIntervalRef.current); silenceIntervalRef.current = null }
    setSilenceProgress(0)
    setIsPaused(true)
    isPausedRef.current = true
  }

  function handleResume() {
    setIsPaused(false)
    isPausedRef.current = false
    resetSilenceTimerRef.current?.()
  }

  function listenForAnswer(lang = bcp47(locale), question?: ScriptQuestion): Promise<string> {
    return new Promise(resolve => {
      const SpeechRecognition =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
      if (!SpeechRecognition) { resolve(''); return }

      // Abort immediately if interview was cancelled
      if (interviewAbortRef.current?.signal.aborted) { resolve(''); return }

      const recognition = new SpeechRecognition()
      recognition.continuous     = true
      recognition.interimResults = true
      recognition.lang           = lang

      const parts: string[] = []
      let resolved           = false
      let speculativeTimer: ReturnType<typeof setTimeout> | null = null

      recogRef.current = { recognition, controller: null }
      setIsListening(true)
      setStatusMsg('')
      setIsPaused(false)
      isPausedRef.current = false
      setSilenceProgress(0)

      const INITIAL_SILENCE_MS = 10000
      const ANSWER_SILENCE_MS  = 3500
      const TICK_MS = 50

      function clearSilenceTimers() {
        if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null }
        if (silenceIntervalRef.current) { clearInterval(silenceIntervalRef.current); silenceIntervalRef.current = null }
      }

      function resetSilenceTimer(initial = false) {
        if (isPausedRef.current) return
        clearSilenceTimers()
        const duration = initial ? INITIAL_SILENCE_MS : ANSWER_SILENCE_MS
        let elapsed = 0
        setSilenceProgress(100)
        silenceIntervalRef.current = setInterval(() => {
          elapsed += TICK_MS
          setSilenceProgress(Math.max(0, 100 - (elapsed / duration) * 100))
        }, TICK_MS)
        silenceTimerRef.current = setTimeout(() => {
          clearSilenceTimers()
          setSilenceProgress(0)
          recogRef.current = null
          try { recognition.stop() } catch { finish(parts.join(' ')) }
        }, duration)
      }

      resetSilenceTimer(true)
      resetSilenceTimerRef.current = () => resetSilenceTimer(false)

      // Also resolve if interview is aborted externally
      const abortHandler = () => finish('')
      interviewAbortRef.current?.signal.addEventListener('abort', abortHandler)

      function finish(finalText: string) {
        if (resolved) return
        resolved = true
        clearSilenceTimers()
        setSilenceProgress(0)
        if (speculativeTimer) clearTimeout(speculativeTimer)
        interviewAbortRef.current?.signal.removeEventListener('abort', abortHandler)
        recogRef.current = null
        setIsListening(false)
        setIsPaused(false)
        isPausedRef.current = false
        resolve(finalText.trim())
      }

      function maybeStartSpeculative(interimText: string) {
        if (speculativeRef.current || !question) return
        if (interimText.split(/\s+/).length < 10) return
        if (speculativeTimer) clearTimeout(speculativeTimer)
        speculativeTimer = setTimeout(() => {
          if (resolved || speculativeRef.current) return
          const ac = new AbortController()
          const promise = fetchElaborationPress(question.text, interimText, question.probing_instructions, ac.signal)
          speculativeRef.current = { controller: ac, promise, forText: interimText }
        }, 800)
      }

      recognition.onresult = (event: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
        resetSilenceTimer(false)
        let currentInterim = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) parts.push(event.results[i][0].transcript)
          else currentInterim += event.results[i][0].transcript
        }
        maybeStartSpeculative((parts.join(' ') + ' ' + currentInterim).trim())
      }

      recognition.onend = () => {
        if (recogRef.current?.recognition === recognition) {
          try { recognition.start(); return } catch { /* can't restart */ }
        }
        clearSilenceTimers()
        setSilenceProgress(0)
        finish(parts.join(' '))
      }

      recognition.onerror = (event: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
        clearSilenceTimers()
        setSilenceProgress(0)
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          setStatusMsg('Microphone access denied — allow it in browser settings.')
          recogRef.current = null
          finish('')
          return
        }
        recogRef.current = null
        finish(parts.join(' '))
      }

      recognition.start()
    })
  }

  async function getElaborationPress(question: ScriptQuestion, answer: string): Promise<string> {
    const spec = speculativeRef.current
    speculativeRef.current = null
    if (spec) {
      if (wordSimilarity(spec.forText, answer) >= 0.55) {
        spec.controller.abort()
        try { return await spec.promise } catch { /* fall through */ }
      } else {
        spec.controller.abort()
      }
    }
    return fetchElaborationPress(question.text, answer, question.probing_instructions)
  }

  // ── Close handler — shows transcript if interview was underway ───────────────

  function handleClose() {
    if (phase === 'interviewing') {
      interviewAbortRef.current?.abort()
      audioRef.current?.pause()
      stopListeningInternal()
      speculativeRef.current?.controller.abort()
      // If any exchanges were captured, show them rather than silently closing
      if (transcriptRef.current.length > 0) {
        setPhase('complete')
        setCurrentQ('')
        return
      }
    }
    onClose()
  }

  // ── Interview orchestration ───────────────────────────────────────────────────

  // Called synchronously from the "Continue →" button click so that the
  // AudioContext captures the user gesture before any async boundary.
  function startBriefingAudio() {
    const BRIEFING =
      "Hi, I'm Avery — and I'll be your interviewer today. " +
      "Before we begin, let me run through how this works. " +
      "This is a verbal interview — just speak naturally and in your own words. " +
      "After each answer, a brief pause will move us to the next question, or tap Done whenever you're ready. " +
      "If you need a moment to gather your thoughts, just tap the Hold button to pause the timer. " +
      "And wherever you can, use real examples — specific situations that have actually happened are far more useful than general impressions. " +
      "... Right, let's begin."

    // AudioContext created synchronously retains user-gesture authorisation
    // across the async fetch that follows — unlike new Audio().play().
    const ctx = new AudioContext()
    briefingCtxRef.current = ctx
    setIsBriefing(true)

    fetch(`${API_BASE}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ text: BRIEFING, voice_id: AVERY_VOICE_ID }),
    })
      .then(res => res.ok ? res.arrayBuffer() : Promise.reject(res.status))
      .then(buf => ctx.decodeAudioData(buf))
      .then(audioBuffer => new Promise<void>(resolve => {
        const source = ctx.createBufferSource()
        source.buffer = audioBuffer
        source.connect(ctx.destination)
        source.onended = () => resolve()
        source.start()
      }))
      .catch(() => { /* network/decode error — briefing plays silently */ })
      .finally(() => {
        ctx.close().catch(() => {})
        briefingCtxRef.current = null
        setIsBriefing(false)
      })
  }

  const runInterview = useCallback(async () => {
    if (!script) return

    stopMicTestInternal()
    transcriptRef.current = []
    setTranscript([])
    progressRef.current = 0

    const ac = new AbortController()
    interviewAbortRef.current = ac
    const aborted = () => ac.signal.aborted

    setPhase('interviewing')
    setCurrentQ(script.welcome_message)
    await speakText(script.welcome_message)
    if (aborted()) return

    let qNum = 0
    for (const section of script.sections) {
      for (const question of section.questions) {
        qNum++
        if (aborted()) return

        progressRef.current = qNum
        setProgress(p => ({ ...p, current: qNum }))
        setCurrentQ(question.text)
        await speakText(question.text)
        if (aborted()) return

        let answer = await listenForAnswer(bcp47(locale), question)
        if (aborted()) return

        // No response — repeat the question once with a gentle lead-in
        if (!answer.trim()) {
          const prompt = NO_RESPONSE_PROMPTS[Math.floor(Math.random() * NO_RESPONSE_PROMPTS.length)]
          setCurrentQ(prompt + question.text)
          await speakText(prompt + question.text)
          if (aborted()) return
          answer = await listenForAnswer(bcp47(locale), question)
          if (aborted()) return
        }

        const needsElaboration =
          answer.trim().length > 0 &&
          question.evasion_signals.some(sig => answer.toLowerCase().includes(sig.toLowerCase()))

        let followUpCount = 0

        if (needsElaboration) {
          // An empty press is the server saying it went over budget and produced none. It
          // must not be spoken or displayed: doing so leaves the interviewee recording in
          // silence in front of a blank question, and records an exchange with no question.
          const pressText = await getElaborationPress(question, answer)
          if (aborted()) return
          if (pressText) {
            setCurrentQ(pressText)
            await speakText(pressText)
            if (aborted()) return
            const elaborationAnswer = await listenForAnswer(bcp47(locale))
            if (aborted()) return
            addToTranscript(pressText, elaborationAnswer)
            answer = `${answer} ${elaborationAnswer}`.trim()
            followUpCount++
          }
        } else {
          speculativeRef.current?.controller.abort()
          speculativeRef.current = null
        }

        addToTranscript(question.text, answer)

        while (followUpCount < question.follow_up_count && question.follow_up_branches[followUpCount]) {
          if (aborted()) return
          const branch = question.follow_up_branches[followUpCount]
          setCurrentQ(branch)
          await speakText(branch)
          if (aborted()) return
          const branchAnswer = await listenForAnswer(bcp47(locale))
          if (aborted()) return
          addToTranscript(branch, branchAnswer)
          followUpCount++
        }
      }
    }

    if (aborted()) return

    setCurrentQ(script.closing_message)
    await speakText(script.closing_message)
    setPhase('complete')
    setCurrentQ('')
  }, [script]) // eslint-disable-line react-hooks/exhaustive-deps

  function addToTranscript(question: string, answer: string) {
    const pair: QAPair = { question, answer }
    transcriptRef.current = [...transcriptRef.current, pair]
    setTranscript([...transcriptRef.current])
  }

  function copyTranscript() {
    const text = transcriptRef.current
      .map(({ question, answer }) => `Q: ${question}\nA: ${answer}`)
      .join('\n\n')
    navigator.clipboard.writeText(text).catch(() => {})
  }

  // ── Speaking indicator ────────────────────────────────────────────────────────

  const isBusy = isFetching || isPlaying

  const speakingIndicator = isFetching
    ? <SpinnerIcon />
    : isPlaying
    ? <WaveformIcon />
    : isListening
    ? <Mic size={18} className="text-emerald-300 animate-pulse" />
    : null

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      onClick={e => { if (e.target === e.currentTarget) handleClose() }}
    >
      <div className="relative w-full max-w-3xl rounded-2xl overflow-hidden shadow-2xl bg-slate-900 flex flex-col max-h-[90vh]">

        <button
          onClick={handleClose}
          className="absolute top-4 right-4 z-10 text-slate-400 hover:text-white transition-colors"
          aria-label="Close"
        >
          <X size={20} />
        </button>

        {/* ── Loading ── */}
        {phase === 'loading' && (
          <div className="flex-1 flex items-center justify-center py-20">
            <p className="text-slate-400 animate-pulse">Loading interview script…</p>
          </div>
        )}

        {/* ── Error ── */}
        {phase === 'error' && (
          <div className="flex-1 flex flex-col items-center justify-center py-16 px-8 text-center gap-4">
            <MicOff size={32} className="text-red-400" />
            <p className="text-red-300 font-medium">Unable to load test script</p>
            <p className="text-slate-400 text-sm">{errorMsg}</p>
            <button onClick={handleClose} className="mt-2 px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-sm">Close</button>
          </div>
        )}

        {/* ── Setup ── */}
        {phase === 'setup' && script && (
          <div className="flex flex-col gap-6 px-8 py-8">
            <div className="flex items-center gap-4">
              <img src={AVERY_HIRES} alt="Avery Singh" className="w-16 h-16 rounded-full object-cover ring-2 ring-teal-500/40 flex-shrink-0" />
              <div>
                <p className="text-teal-400 text-[10px] font-bold uppercase tracking-widest mb-0.5">Device Setup</p>
                <h2 className="text-white font-semibold">Check your audio before starting</h2>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {/* Microphone */}
              <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 space-y-3">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5"><Mic size={11} /> Microphone</p>
                <select
                  value={selectedInput}
                  onChange={e => { setSelectedInput(e.target.value); stopMicTestInternal() }}
                  className="w-full bg-slate-900 border border-slate-600 text-slate-200 text-xs rounded-lg px-2.5 py-1.5 outline-none focus:border-teal-500"
                >
                  {audioInputs.length === 0
                    ? <option value="">No microphones found</option>
                    : audioInputs.map(d => <option key={d.deviceId} value={d.deviceId}>{d.label || `Microphone ${d.deviceId.slice(0,8)}`}</option>)
                  }
                </select>
                {isMicTesting && (
                  <div>
                    <div className="w-full bg-slate-700 rounded-full h-2 overflow-hidden">
                      <div className="h-2 rounded-full bg-teal-400 transition-all duration-75" style={{ width: `${Math.round(micLevel * 100)}%` }} />
                    </div>
                    <p className="text-[10px] text-slate-500 mt-1">Speak to check level</p>
                  </div>
                )}
                <button
                  onClick={toggleMicTest}
                  className={`text-xs font-medium transition-colors ${isMicTesting ? 'text-red-400 hover:text-red-300' : 'text-teal-400 hover:text-teal-300'}`}
                >
                  {isMicTesting ? 'Stop test' : 'Test microphone'}
                </button>
                {statusMsg && <p className="text-[10px] text-amber-400">{statusMsg}</p>}
              </div>

              {/* Speaker */}
              <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 space-y-3">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5"><Volume2 size={11} /> Speaker</p>
                {audioOutputs.length > 0 ? (
                  <select
                    value={selectedOutput}
                    onChange={e => setSelectedOutput(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-600 text-slate-200 text-xs rounded-lg px-2.5 py-1.5 outline-none focus:border-teal-500"
                  >
                    {audioOutputs.map(d => <option key={d.deviceId} value={d.deviceId}>{d.label || `Speaker ${d.deviceId.slice(0,8)}`}</option>)}
                  </select>
                ) : (
                  <p className="text-xs text-slate-500">Default system speaker</p>
                )}
                <button
                  onClick={testSpeaker}
                  disabled={isFetching || isPlaying}
                  className="text-xs font-medium text-teal-400 hover:text-teal-300 transition-colors disabled:opacity-40"
                >
                  {isFetching ? '…' : isPlaying ? 'Playing…' : 'Play test audio'}
                </button>
              </div>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() => { stopMicTestInternal(); startBriefingAudio(); setPhase('ready') }}
                className="px-8 py-2.5 rounded-xl bg-teal-600 hover:bg-teal-500 text-white font-semibold transition-colors"
              >
                Continue →
              </button>
            </div>
          </div>
        )}

        {/* ── Ready ── */}
        {phase === 'ready' && script && (
          <div className="flex flex-col items-center py-8 px-8 gap-5">
            <div className="flex items-center gap-4 w-full max-w-md">
              <img
                src={AVERY_HIRES}
                alt="Avery Singh"
                className="w-16 h-16 rounded-full object-cover ring-2 ring-teal-500/40 shadow-lg flex-shrink-0"
              />
              <div>
                <p className="text-teal-400 text-[10px] font-bold uppercase tracking-widest mb-0.5">Test Interview</p>
                <h2 className="text-white text-lg font-bold leading-snug">{script.node_label}</h2>
                <p className="text-slate-500 text-xs">{progress.total} question{progress.total !== 1 ? 's' : ''} · ElevenLabs voice</p>
              </div>
            </div>

            <div className="bg-slate-800 rounded-xl p-5 w-full max-w-md border border-slate-700">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-3">How it works</p>
              <ul className="space-y-2.5">
                {[
                  'This is a verbal interview — speak naturally and in your own words.',
                  'A pause of a few seconds, or tapping "Done speaking", will move to the next question.',
                  'Need a moment to think? Tap "Hold — I\'m thinking" to pause the timer.',
                  'Use real examples where you can — specific situations that have happened are more useful than general impressions.',
                ].map((tip, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-sm text-slate-300">
                    <span className="w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center text-[10px] font-bold mt-0.5 bg-teal-600 text-white">{i + 1}</span>
                    {tip}
                  </li>
                ))}
              </ul>
            </div>

            {isBriefing ? (
              <div className="flex items-center gap-3 text-slate-400 text-sm">
                <WaveformIcon />
                <span>Avery is speaking…</span>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setPhase('setup')}
                  className="px-4 py-2.5 rounded-xl border border-slate-700 hover:border-slate-500 text-slate-400 hover:text-white text-sm transition-colors"
                >
                  ← Audio setup
                </button>
                <button
                  onClick={runInterview}
                  disabled={isBriefing}
                  className="px-8 py-2.5 rounded-xl bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white font-semibold transition-colors shadow-lg shadow-teal-900/40"
                >
                  Start Test Interview
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── Interviewing ── */}
        {phase === 'interviewing' && (
          <div className="flex flex-col min-h-0">
            <div className="h-1 bg-slate-800 flex-shrink-0">
              <div
                className="h-1 bg-teal-500 transition-all duration-500"
                style={{ width: `${(progress.current / Math.max(progress.total, 1)) * 100}%` }}
              />
            </div>

            <div className="flex flex-1 min-h-0">
              {/* Avery photo */}
              <div className="flex-shrink-0 w-52 bg-slate-950 flex flex-col items-center justify-center gap-4 p-6 border-r border-slate-800">
                <div className="relative">
                  <img
                    src={AVERY_HIRES}
                    alt="Avery Singh"
                    className="w-36 h-36 rounded-full object-cover ring-4 ring-teal-500/30 shadow-xl"
                  />
                  {(isFetching || isPlaying || isListening) && (
                    <span className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-2 border-slate-950 bg-teal-400 animate-pulse" />
                  )}
                </div>
                <div className="text-center">
                  <p className="text-white text-sm font-semibold">Avery Singh</p>
                  <p className="text-slate-500 text-[11px]">AI Interviewer</p>
                </div>
                <div className="text-[10px] text-slate-500">Q {progress.current} / {progress.total}</div>
              </div>

              {/* Question + controls */}
              <div className="flex-1 flex flex-col justify-center px-8 py-8 gap-6">
                {currentQuestion && (
                  <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700">
                    <p className="text-white text-lg leading-relaxed">{currentQuestion}</p>
                  </div>
                )}

                <div className="flex flex-col items-center gap-3">
                  {speakingIndicator}
                  {!isBusy && statusMsg && (
                    <p className="text-xs text-amber-400 text-center max-w-xs">{statusMsg}</p>
                  )}
                  {isListening && (
                    <div className="flex flex-col items-center gap-3 w-full max-w-xs">
                      {/* Silence countdown bar */}
                      {!isPaused && (
                        <div className="w-full">
                          <div className="w-full bg-slate-700 rounded-full h-1.5 overflow-hidden">
                            <div
                              className="h-1.5 rounded-full bg-teal-500 transition-none"
                              style={{ width: `${silenceProgress}%` }}
                            />
                          </div>
                          <p className="text-[11px] text-slate-500 text-center mt-1">
                            {silenceProgress > 0 ? 'Moving on when you stop speaking…' : 'Waiting for your response…'}
                          </p>
                        </div>
                      )}
                      {isPaused && (
                        <p className="text-sm text-amber-400 font-medium">Interview paused — take your time.</p>
                      )}
                      <button
                        onClick={submitAnswer}
                        className="px-8 py-3 rounded-full bg-teal-600 hover:bg-teal-500 text-white font-semibold transition-colors flex items-center gap-2 shadow-lg shadow-teal-900/30"
                      >
                        <CheckCircle2 size={18} /> Done speaking
                      </button>
                      {isPaused ? (
                        <button
                          onClick={handleResume}
                          className="flex items-center gap-2 text-sm font-medium text-teal-400 bg-teal-900/30 hover:bg-teal-900/50 border border-teal-800/60 rounded-full px-4 py-2 transition-colors"
                          aria-label="Resume - I'm good, let's continue"
                        >
                          <Play size={14} />Ready — continue
                        </button>
                      ) : (
                        <button
                          onClick={handlePause}
                          className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-full px-4 py-2 transition-colors"
                          aria-label="Pause - I need a moment to think"
                        >
                          <Pause size={14} />Hold — I'm thinking
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {transcript.length > 0 && (
                  <div className="border-t border-slate-800 pt-4">
                    <button
                      onClick={() => setShowTx(v => !v)}
                      className="flex items-center gap-1.5 text-[11px] text-slate-500 hover:text-slate-300 transition-colors"
                    >
                      {showTranscript ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                      Transcript so far ({transcript.length} exchange{transcript.length !== 1 ? 's' : ''})
                    </button>
                    {showTranscript && (
                      <div className="mt-3 space-y-3 max-h-40 overflow-y-auto pr-1">
                        {transcript.map((pair, i) => (
                          <div key={i} className="space-y-1">
                            <p className="text-[11px] text-teal-400 font-medium truncate">Q: {pair.question}</p>
                            <p className="text-[11px] text-slate-400 line-clamp-2">A: {pair.answer || '—'}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Complete ── */}
        {phase === 'complete' && (
          <div className="flex flex-col max-h-[90vh]">
            <div className="flex items-center gap-4 px-8 py-6 border-b border-slate-800 flex-shrink-0">
              <img src={AVERY_HIRES} alt="Avery Singh" className="w-14 h-14 rounded-full object-cover ring-2 ring-teal-500/40 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-teal-400 flex-shrink-0" />
                  <p className="text-white font-semibold">Test interview complete</p>
                </div>
                <p className="text-slate-400 text-sm mt-0.5">
                  {transcript.length} exchange{transcript.length !== 1 ? 's' : ''} recorded
                </p>
              </div>
              <button
                onClick={copyTranscript}
                className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 rounded-lg px-3 py-2 transition-colors flex-shrink-0"
              >
                <Copy size={12} /> Copy transcript
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-8 py-6 space-y-5">
              {transcript.map((pair, i) => (
                <div key={i} className="space-y-2">
                  <div className="flex items-start gap-3">
                    <img src={AVERY_HIRES} alt="Avery" className="w-6 h-6 rounded-full object-cover flex-shrink-0 mt-0.5 opacity-80" />
                    <div className="bg-slate-800 rounded-xl rounded-tl-none px-4 py-3 flex-1">
                      <p className="text-slate-200 text-sm leading-relaxed">{pair.question}</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 pl-9 flex-row-reverse">
                    <div className="bg-teal-900/40 border border-teal-800/40 rounded-xl rounded-tr-none px-4 py-3 flex-1">
                      {editingIdx === i ? (
                        <div className="space-y-2">
                          <textarea
                            className="w-full text-sm text-slate-200 bg-slate-800 border border-teal-600/50 rounded-lg p-2 resize-none focus:outline-none focus:ring-1 focus:ring-teal-500"
                            rows={4}
                            value={editText}
                            onChange={e => setEditText(e.target.value)}
                            autoFocus
                          />
                          <div className="flex gap-2 justify-end">
                            <button
                              onClick={() => setEditingIdx(null)}
                              className="flex items-center gap-1 text-xs text-slate-400 hover:text-white px-2.5 py-1 border border-slate-700 rounded-lg transition-colors"
                            >
                              <X size={10} /> Cancel
                            </button>
                            <button
                              onClick={() => {
                                const updated = [...transcript]
                                updated[i] = { ...updated[i], answer: editText }
                                setTranscript(updated)
                                setEditingIdx(null)
                              }}
                              className="flex items-center gap-1 text-xs text-white px-2.5 py-1 bg-teal-600 hover:bg-teal-500 rounded-lg transition-colors"
                            >
                              <Check size={10} /> Save
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          <p className="flex-1 text-slate-200 text-sm leading-relaxed">
                            {pair.answer || <span className="text-slate-500 italic">No response recorded</span>}
                          </p>
                          <button
                            onClick={() => { setEditingIdx(i); setEditText(pair.answer) }}
                            className="flex-shrink-0 p-1 text-slate-600 hover:text-teal-400 transition-colors rounded"
                            title="Edit this response"
                          >
                            <Pencil size={12} />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              {transcript.length === 0 && (
                <p className="text-slate-500 text-sm text-center py-8">No responses recorded.</p>
              )}

              {/* Send copy */}
              <div className="border-t border-slate-800 pt-5">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={sendCopy}
                    onChange={e => setSendCopy(e.target.checked)}
                    className="w-4 h-4 rounded accent-teal-500"
                  />
                  <span className="text-sm text-slate-300">Send a copy of this transcript to me</span>
                </label>
                {sendCopy && (
                  <div className="mt-3 flex gap-2">
                    <input
                      type="email"
                      placeholder="Your email address"
                      value={copyEmail}
                      onChange={e => setCopyEmail(e.target.value)}
                      className="flex-1 text-sm bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-500 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-teal-500"
                    />
                    <button
                      disabled={!copyEmail}
                      onClick={() => {
                        const lines = transcript.map((p, idx) =>
                          `Q${idx + 1}: ${p.question}\nA${idx + 1}: ${p.answer || 'No response recorded'}`
                        ).join('\n\n')
                        const subject = encodeURIComponent('Your interview transcript')
                        const body = encodeURIComponent(`Thank you for completing the interview.\n\nHere is a copy of your responses:\n\n${lines}`)
                        window.open(`mailto:${copyEmail}?subject=${subject}&body=${body}`)
                      }}
                      className="px-4 py-2 text-sm bg-teal-600 hover:bg-teal-500 disabled:opacity-40 text-white rounded-lg transition-colors"
                    >
                      Send
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div className="flex items-center justify-between px-8 py-5 border-t border-slate-800 flex-shrink-0">
              <button
                onClick={() => { setPhase('ready'); setTranscript([]); transcriptRef.current = []; setEditingIdx(null); setSendCopy(false); setCopyEmail('') }}
                className="text-sm text-slate-400 hover:text-white transition-colors"
              >
                Run again
              </button>
              <button
                onClick={handleClose}
                className="px-6 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-sm font-medium transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function SpinnerIcon() {
  return (
    <svg className="animate-spin text-slate-400" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  )
}

function WaveformIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-teal-300">
      <line x1="2"  y1="12" x2="2"  y2="12" />
      <line x1="6"  y1="8"  x2="6"  y2="16" />
      <line x1="10" y1="4"  x2="10" y2="20" />
      <line x1="14" y1="8"  x2="14" y2="16" />
      <line x1="18" y1="10" x2="18" y2="14" />
      <line x1="22" y1="12" x2="22" y2="12" />
    </svg>
  )
}
