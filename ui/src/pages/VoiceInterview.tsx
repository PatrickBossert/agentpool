import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import type { InterviewSession, InterviewScript, InterviewBranding, MaturityRating, SectionMaturityRating } from '../types'

// webkit speech recognition types (Chrome/Safari vendor prefix)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const webkitSpeechRecognition: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const SpeechRecognitionEvent: any

type Phase = 'loading' | 'mic_setup' | 'ready' | 'interviewing' | 'rating' | 'complete' | 'error'
type MicStatus = 'no_device' | 'permission_needed' | 'permission_denied' | 'testing' | 'ready'

const BASE = '/api'

export default function VoiceInterview() {
  const { sessionToken } = useParams<{ sessionToken: string }>()
  const [phase, setPhase] = useState<Phase>('loading')
  const [sessionData, setSessionData] = useState<{ session: InterviewSession; script: InterviewScript } | null>(null)
  const [currentQuestion, setCurrentQuestion] = useState<string>('')
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const [statusMessage, setStatusMessage] = useState<string>('')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [branding, setBranding] = useState<InterviewBranding | null>(null)
  const [isListening, setIsListening] = useState(false)
  const [pendingRating, setPendingRating] = useState<MaturityRating | null>(null)
  const [micStatus, setMicStatus] = useState<MicStatus>('no_device')
  const [audioLevel, setAudioLevel] = useState(0)
  const [availableDevices, setAvailableDevices] = useState<MediaDeviceInfo[]>([])
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('')
  const [isMicTesting, setIsMicTesting] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [interimText, setInterimText] = useState('')
  const recognitionRef = useRef<any>(null)
  const restartAnswerRef = useRef(false)
  const qaRef = useRef<{ question: string; answer: string }[]>([])
  const sectionRatingsRef = useRef<SectionMaturityRating[]>([])
  const ratingResolveRef = useRef<((rating: number) => void) | null>(null)
  const interviewLangRef = useRef<string>('en-GB')
  const micStreamRef = useRef<MediaStream | null>(null)
  const micLevelTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    fetchSession()
  }, [sessionToken])

  // Stop mic test stream when leaving mic_setup or ready phase
  useEffect(() => {
    if (phase !== 'mic_setup' && phase !== 'ready') stopMicTest()
  }, [phase])

  // Load audio input devices when entering the ready phase
  useEffect(() => {
    if (phase === 'ready') loadAudioDevices()
  }, [phase])

  async function checkMicDevices(): Promise<boolean> {
    if (!navigator.mediaDevices?.enumerateDevices) {
      setMicStatus('no_device')
      return false
    }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      const inputs = devices.filter(d => d.kind === 'audioinput')
      if (inputs.length === 0) {
        setMicStatus('no_device')
        return false
      }
      // No labels → browser hasn't been granted permission yet
      if (!inputs.some(d => d.label !== '')) {
        setMicStatus('permission_needed')
        return false
      }
      // Labels are present (permission was granted), but the device might still be
      // physically missing (disconnected headset, virtual device, etc.). Probe with
      // getUserMedia - this is silent when permission was already granted.
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
        stream.getTracks().forEach(t => t.stop())
        return true
      } catch {
        setMicStatus('no_device')
        return false
      }
    } catch {
      setMicStatus('no_device')
      return false
    }
  }

  async function loadAudioDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      const inputs = devices.filter(d => d.kind === 'audioinput')
      setAvailableDevices(inputs)
      // Only set a default if nothing is selected yet
      if (inputs.length > 0) setSelectedDeviceId(prev => prev || inputs[0].deviceId)
    } catch { /* ignore */ }
  }

  async function testMicrophone(deviceId?: string) {
    setMicStatus('testing')
    setIsMicTesting(false)
    stopMicTest()
    try {
      const audioConstraints: MediaTrackConstraints | boolean = deviceId
        ? { deviceId: { exact: deviceId } }
        : true
      const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints, video: false })
      micStreamRef.current = stream

      // Live audio-level meter via Web Audio API
      const ctx = new AudioContext()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 256
      ctx.createMediaStreamSource(stream).connect(analyser)
      const buf = new Uint8Array(analyser.frequencyBinCount)
      micLevelTimerRef.current = setInterval(() => {
        analyser.getByteFrequencyData(buf)
        const avg = buf.reduce((a, b) => a + b, 0) / buf.length
        setAudioLevel(avg / 255)
      }, 50)

      setMicStatus('ready')
      setIsMicTesting(true)
    } catch (err: unknown) {
      const name = err instanceof Error ? err.name : ''
      setMicStatus(name === 'NotAllowedError' || name === 'SecurityError' ? 'permission_denied' : 'no_device')
      setIsMicTesting(false)
    }
  }

  function stopMicTest() {
    if (micLevelTimerRef.current) { clearInterval(micLevelTimerRef.current); micLevelTimerRef.current = null }
    micStreamRef.current?.getTracks().forEach(t => t.stop())
    micStreamRef.current = null
    setAudioLevel(0)
    setIsMicTesting(false)
  }

  async function fetchSession() {
    try {
      const res = await fetch(`${BASE}/interviews/${sessionToken}`)
      if (!res.ok) throw new Error(`Failed to load interview (${res.status})`)
      const data = await res.json()
      const total = data.script.sections.reduce(
        (acc: number, s: { questions: unknown[] }) => acc + s.questions.length,
        0
      )
      setProgress({ current: 0, total })
      setSessionData(data)
      setBranding(data.branding ?? null)
      // Inline maturity ratings are embedded in section.maturity_rating — no separate questionnaire

      const micOk = await checkMicDevices()
      setPhase(micOk ? 'ready' : 'mic_setup')
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unknown error')
      setPhase('error')
    }
  }

  async function speakText(text: string, voiceId: string): Promise<void> {
    setStatusMessage('Speaking…')
    const res = await fetch(`${BASE}/interviews/${sessionToken}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice_id: voiceId }),
    })
    if (!res.ok) {
      // Non-fatal: skip audio, continue
      console.warn('speak endpoint error', res.status)
      return
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    await new Promise<void>((resolve) => {
      const audio = new Audio(url)
      audio.onended = () => {
        URL.revokeObjectURL(url)
        resolve()
      }
      audio.onerror = () => {
        URL.revokeObjectURL(url)
        resolve()
      }
      audio.play().catch(() => resolve())
    })
    setStatusMessage('')
  }

  function listenForAnswer(lang: string = 'en-GB'): Promise<string> {
    return new Promise((resolve) => {
      const SpeechRecognition =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (window as any).SpeechRecognition ||
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (window as any).webkitSpeechRecognition
      if (!SpeechRecognition) {
        resolve('')
        return
      }
      const recognition = new SpeechRecognition()
      recognition.continuous = true
      recognition.interimResults = true
      recognition.lang = lang

      recognitionRef.current = recognition

      const parts: string[] = []
      let resolved = false

      function finish() {
        if (resolved) return
        resolved = true
        recognitionRef.current = null
        setIsListening(false)
        setStatusMessage('')
        setInterimText('')
        resolve(parts.join(' ').trim())
      }

      setStatusMessage('Listening…')
      setIsListening(true)

      let silenceTimer: ReturnType<typeof setTimeout> | null = null

      function resetSilenceTimer() {
        if (silenceTimer) clearTimeout(silenceTimer)
        // Clear ref first so onend knows this stop is intentional (not a Chrome timeout)
        silenceTimer = setTimeout(() => {
          recognitionRef.current = null
          try { recognition.stop() } catch { finish() }
        }, 3000)
      }

      recognition.onresult = (event: typeof SpeechRecognitionEvent) => {
        resetSilenceTimer()
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            parts.push(event.results[i][0].transcript)
          }
        }
        // Show live transcript to user
        const interim = Array.from(event.results as unknown[])
          .slice(event.resultIndex)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .filter((r: any) => !r.isFinal)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .map((r: any) => r[0].transcript)
          .join(' ')
        setInterimText([...parts, interim].join(' ').trim())
      }

      // onend fires after every stop - including Chrome's internal timeouts.
      // Only finish if the ref was cleared (user/silence-timer initiated stop).
      // Otherwise restart to keep listening.
      recognition.onend = () => {
        if (silenceTimer) clearTimeout(silenceTimer)
        if (recognitionRef.current === recognition) {
          // Chrome stopped us internally - restart to keep listening
          try {
            recognition.start()
            return
          } catch {
            // Can't restart (e.g., permission revoked mid-session)
          }
        }
        finish()
      }

      recognition.onerror = (event: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
        if (silenceTimer) clearTimeout(silenceTimer)
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          // Microphone permission denied - show message, block auto-advance
          setStatusMessage('⚠️ Microphone access denied. Allow microphone access in your browser, then click ✓ Done to continue.')
          recognitionRef.current = null  // prevent onend from restarting
          return
        }
        // For no-speech, network, etc. - clear ref so onend won't restart
        recognitionRef.current = null
      }

      recognition.start()
    })
  }

  function submitAnswer() {
    // Clear ref BEFORE stopping so onend knows this was user-initiated (not a Chrome restart)
    const r = recognitionRef.current
    recognitionRef.current = null
    try { r?.stop() } catch { /* already stopped */ }
  }

  function restartAnswer() {
    restartAnswerRef.current = true
    submitAnswer()
  }

  async function listenWithRestart(lang: string = 'en-GB'): Promise<string> {
    restartAnswerRef.current = false
    // eslint-disable-next-line no-constant-condition
    while (true) {
      setInterimText('')
      const answer = await listenForAnswer(lang)
      if (!restartAnswerRef.current) return answer
      restartAnswerRef.current = false
      setStatusMessage('Restarting…')
      await new Promise(r => setTimeout(r, 300))
      setStatusMessage('')
    }
  }

  async function getElaborationPress(
    questionText: string,
    responseText: string,
    probingInstructions: string
  ): Promise<string> {
    try {
      const res = await fetch(`${BASE}/interviews/${sessionToken}/elaboration-press`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question_text: questionText, response_text: responseText, probing_instructions: probingInstructions }),
      })
      if (!res.ok) return "Could you tell me more about that?"
      const data = await res.json()
      return data.press_text ?? "Could you tell me more about that?"
    } catch {
      return "Could you tell me more about that?"
    }
  }

  async function submitResponses(ratings: SectionMaturityRating[]) {
    setStatusMessage('Saving your responses…')
    try {
      const res = await fetch(`${BASE}/interviews/${sessionToken}/complete`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          qa_pairs: qaRef.current,
          ratings: ratings.length > 0 ? ratings : undefined,
        }),
      })
      if (!res.ok) console.warn('complete endpoint returned', res.status)
    } catch (err) {
      console.error('Failed to submit responses', err)
    }
    setPhase('complete')
    setStatusMessage('')
    setCurrentQuestion('')
  }

  const DEFAULT_VOICE_CONFIG = { elevenlabs_voice_id: '21m00Tcm4TlvDq8ikWAM', language: 'en', country_code: 'GB' }

  async function runInterview() {
    if (!sessionData) return
    const { session, script } = sessionData
    const voiceConfig = session.voice_config ?? DEFAULT_VOICE_CONFIG
    const voiceId = voiceConfig.elevenlabs_voice_id
    const lang = `${voiceConfig.language}-${voiceConfig.country_code}`
    interviewLangRef.current = lang

    setPhase('interviewing')

    // Activate session
    await fetch(`${BASE}/interviews/${sessionToken}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'active' }),
    })

    // Welcome
    setCurrentQuestion(script.welcome_message)
    await speakText(script.welcome_message, voiceId)

    let questionNumber = 0

    sectionRatingsRef.current = []

    for (const section of script.sections) {
      for (const question of section.questions) {
        questionNumber++
        setProgress(p => ({ ...p, current: questionNumber }))
        setCurrentQuestion(question.text)

        // Ask the question
        await speakText(question.text, voiceId)

        // Record primary answer
        let answer = await listenWithRestart(lang)

        const needsElaboration =
          answer.trim().length > 0 &&
          question.evasion_signals.some(sig => answer.toLowerCase().includes(sig.toLowerCase()))

        let followUpCount = 0

        if (needsElaboration) {
          // Press for elaboration
          const pressText = await getElaborationPress(question.text, answer, question.probing_instructions)
          setCurrentQuestion(pressText)
          await speakText(pressText, voiceId)
          const followUpAnswer = await listenWithRestart(lang)
          qaRef.current.push({ question: pressText, answer: followUpAnswer })
          answer = `${answer} ${followUpAnswer}`.trim()
          followUpCount++
        }

        // Push primary Q&A before follow-up branches
        qaRef.current.push({ question: question.text, answer })

        // Pre-scripted follow-up branches
        while (followUpCount < question.follow_up_count && question.follow_up_branches[followUpCount]) {
          const branch = question.follow_up_branches[followUpCount]
          setCurrentQuestion(branch)
          await speakText(branch, voiceId)
          const branchAnswer = await listenWithRestart(lang)
          qaRef.current.push({ question: branch, answer: branchAnswer })
          followUpCount++
        }
      }

      // After all questions in a section, capture inline maturity rating if present (L1/L2 only)
      if (section.maturity_rating) {
        const mr = section.maturity_rating
        await speakText(mr.prompt, voiceId)
        const rating = await collectInlineRating(mr)
        sectionRatingsRef.current.push({ section_title: section.title, dimension: mr.dimension, rating })
        setPhase('interviewing')
      }
    }

    // Closing
    setCurrentQuestion(script.closing_message)
    await speakText(script.closing_message, voiceId)

    await submitResponses(sectionRatingsRef.current)
  }

  function parseRatingFromVoice(text: string): number | null {
    const t = text.toLowerCase().trim()
    const words: Record<string, number> = {
      zero: 0, nought: 0, naught: 0,
      one: 1,
      two: 2,
      three: 3,
      four: 4,
    }
    const digit = t.match(/\b([0-4])\b/)
    if (digit) return parseInt(digit[1])
    for (const [word, val] of Object.entries(words)) {
      if (t.includes(word)) return val
    }
    return null
  }

  // Pauses the interview loop, shows the rating picker, and auto-listens for a spoken number.
  // Resolves when the user either speaks a valid rating or taps one.
  function collectInlineRating(mr: MaturityRating): Promise<number> {
    setPendingRating(mr)
    setPhase('rating')
    const promise = new Promise<number>(resolve => { ratingResolveRef.current = resolve })
    // Kick off voice listen — two attempts before falling back to tap-only
    void attemptVoiceRating(2)
    return promise
  }

  async function attemptVoiceRating(attemptsLeft: number) {
    if (attemptsLeft <= 0) {
      setStatusMessage('Please tap a rating below.')
      return
    }
    const lang = interviewLangRef.current
    setStatusMessage('Listening for your rating…')
    const spoken = await listenForAnswer(lang)
    // Guard: if user already tapped while we were listening, the resolve has fired — bail out
    if (!ratingResolveRef.current) return
    const parsed = parseRatingFromVoice(spoken)
    if (parsed !== null) {
      selectRating(parsed)
    } else {
      setStatusMessage('I didn\'t catch that — please say a number from 0 to 4, or tap below.')
      await attemptVoiceRating(attemptsLeft - 1)
    }
  }

  function selectRating(value: number) {
    if (!ratingResolveRef.current) return  // already resolved by voice
    ratingResolveRef.current(value)
    ratingResolveRef.current = null
    setPendingRating(null)
    setStatusMessage('')
    // phase reverts to 'interviewing' in the loop after collectInlineRating resolves
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  if (phase === 'loading') {
    return (
      <div className="h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
        {branding?.header_image_url && (
          <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
        )}
        <p className="text-gray-500 text-lg">Loading your interview…</p>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
        <div className="text-center">
          {branding?.header_image_url && (
            <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
          )}
          <p className="text-red-600 text-xl font-semibold mb-2">Unable to load interview</p>
          <p className="text-gray-500">{errorMessage}</p>
        </div>
      </div>
    )
  }

  if (phase === 'complete') {
    return (
      <div className="h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
        <div className="text-center max-w-md">
          {branding?.header_image_url && (
            <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
          )}
          <div className="text-5xl mb-4">✓</div>
          <h1 className="text-2xl font-bold text-gray-800 mb-2">Thank you!</h1>
          <p className="text-gray-500">Your responses have been recorded. You may now close this window.</p>
        </div>
      </div>
    )
  }

  if (phase === 'rating' && pendingRating) {
    const mr = pendingRating
    const primaryColor = branding?.primary_color ?? '#0d9488'
    return (
      <div className="h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
        <div className="max-w-xl w-full">
          {branding?.header_image_url && (
            <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
          )}
          <p className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: primaryColor }}>
            Quick rating — {mr.dimension}
          </p>
          <p className="text-gray-800 font-medium mb-6">{mr.prompt}</p>
          <div className="space-y-3">
            {([0, 1, 2, 3, 4] as const).map(score => (
              <button
                key={score}
                onClick={() => selectRating(score)}
                className="w-full text-left bg-white rounded-xl shadow-sm border border-gray-100 px-4 py-3 hover:border-teal-400 hover:shadow transition-all"
              >
                <span
                  className="inline-flex items-center justify-center w-7 h-7 rounded-full text-white text-sm font-bold mr-3"
                  style={{ backgroundColor: primaryColor }}
                >
                  {score}
                </span>
                <span className="text-sm text-gray-700">{mr.scale[String(score)]}</span>
              </button>
            ))}
          </div>
          <div className="mt-6 text-center">
            {isListening ? (
              <p className="text-sm animate-pulse" style={{ color: primaryColor }}>
                Listening… say a number from 0 to 4
              </p>
            ) : statusMessage ? (
              <p className="text-sm text-gray-500">{statusMessage}</p>
            ) : (
              <p className="text-xs text-gray-400">
                Say a number or tap a level — the interview resumes immediately.
              </p>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (phase === 'mic_setup') {
    const statusMessages: Record<MicStatus, { color: string; title: string; body: string }> = {
      no_device:          { color: 'amber',  title: 'No microphone detected',   body: 'Connect a microphone and click Retry.' },
      permission_needed:  { color: 'blue',   title: 'Microphone access needed',  body: 'Click "Test Microphone" and allow access when prompted.' },
      permission_denied:  { color: 'red',    title: 'Microphone access denied',  body: 'Open your browser settings, allow microphone access for this page, then click Retry.' },
      testing:            { color: 'teal',   title: 'Requesting access…',        body: 'Allow microphone access in the browser prompt.' },
      ready:              { color: 'green',  title: 'Microphone ready',          body: 'Speak to see the level indicator below.' },
    }
    const { color, title, body } = statusMessages[micStatus]
    const colorMap: Record<string, string> = {
      amber: 'bg-amber-50 border-amber-200 text-amber-800',
      blue:  'bg-blue-50 border-blue-200 text-blue-800',
      red:   'bg-red-50 border-red-200 text-red-800',
      teal:  'bg-teal-50 border-teal-200 text-teal-800',
      green: 'bg-green-50 border-green-200 text-green-800',
    }

    return (
      <div className="h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
        <div className="text-center max-w-md w-full">
          {branding?.header_image_url && (
            <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
          )}
          <div className="text-4xl mb-4">🎤</div>
          <h1 className="text-2xl font-bold text-gray-800 mb-2">Microphone Setup</h1>
          <p className="text-gray-500 text-sm mb-6">
            This interview records your spoken answers. Please connect a microphone and confirm it is working before starting.
          </p>

          <div className={`border rounded-lg p-4 mb-6 text-left ${colorMap[color]}`}>
            <p className="text-sm font-semibold mb-1">{title}</p>
            <p className="text-sm opacity-80">{body}</p>
          </div>

          {micStatus === 'ready' && (
            <div className="mb-6">
              <p className="text-xs text-gray-400 mb-2">Audio level - speak to check</p>
              <div className="w-full bg-gray-200 rounded-full h-4 overflow-hidden">
                <div
                  className="h-4 rounded-full transition-all duration-75"
                  style={{ width: `${Math.round(audioLevel * 100)}%`, backgroundColor: branding?.primary_color ?? '#0d9488' }}
                />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-3">
            {micStatus !== 'ready' ? (
              <button
                onClick={() => testMicrophone()}
                disabled={micStatus === 'testing'}
                className="bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white font-semibold py-3 px-8 rounded-lg text-lg transition-colors"
                style={{ backgroundColor: branding?.primary_color }}
              >
                {micStatus === 'no_device' || micStatus === 'permission_denied' ? 'Retry' : 'Test Microphone'}
              </button>
            ) : (
              <>
                <button
                  onClick={() => setPhase('ready')}
                  className="bg-teal-600 hover:bg-teal-700 text-white font-semibold py-3 px-8 rounded-lg text-lg transition-colors"
                  style={{ backgroundColor: branding?.primary_color }}
                >
                  Continue to Interview →
                </button>
                <button
                  onClick={() => testMicrophone()}
                  className="text-sm text-gray-400 hover:text-gray-600 py-2"
                >
                  Retry with a different microphone
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (phase === 'ready' && sessionData) {
    return (
      <div className="h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
        <div className="text-center max-w-lg w-full">
          {branding?.header_image_url && (
            <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
          )}

          {/* Interviewer persona */}
          {branding?.interviewer_image_url && (
            <div className="flex flex-col items-center mb-6">
              <img
                src={branding.interviewer_image_url}
                alt={branding.interviewer_name ?? 'Your interviewer'}
                className="w-24 h-24 rounded-full object-cover shadow-md mb-3 ring-4 ring-white"
              />
              <p className="font-semibold text-gray-800" style={{ color: branding.text_color }}>
                {branding.interviewer_name ?? 'Avery Singh'}
              </p>
              {branding.interviewer_tagline && (
                <p className="text-sm text-gray-500 mt-0.5">{branding.interviewer_tagline}</p>
              )}
            </div>
          )}

          <h1 className="text-2xl font-bold text-gray-800 mb-6" style={{ color: branding?.text_color }}>
            {sessionData.script.node_label} Interview
          </h1>

          {/* Interviewee instructions */}
          <div className="bg-white rounded-xl shadow-sm p-5 mb-5 text-left border border-gray-100">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">How it works</p>
            <ul className="space-y-2.5">
              {[
                'This is a verbal interview — speak naturally and in your own words.',
                'A pause of a few seconds, or tapping “✓ Done”, will move to the next question.',
                'Tap “Restart answer” at any time to re-record your response.',
                'Take your time — there are no right or wrong answers.',
              ].map((tip, i) => (
                <li key={i} className="flex items-start gap-2.5 text-sm text-gray-600">
                  <span
                    className="w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-semibold mt-0.5 text-white"
                    style={{ backgroundColor: branding?.primary_color ?? '#0d9488' }}
                  >{i + 1}</span>
                  {tip}
                </li>
              ))}
            </ul>
          </div>

          {/* Microphone selector + inline test */}
          <div className="bg-white rounded-xl shadow-sm p-5 mb-6 text-left">
            <p className="text-sm font-medium text-gray-700 mb-3">🎤 Microphone</p>
            <select
              value={selectedDeviceId}
              onChange={e => { setSelectedDeviceId(e.target.value); stopMicTest() }}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 mb-3 focus:outline-none focus:ring-2 focus:ring-teal-500"
            >
              {availableDevices.length === 0 ? (
                <option value="">No microphones found</option>
              ) : (
                availableDevices.map(d => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label || `Microphone ${d.deviceId.slice(0, 8)}`}
                  </option>
                ))
              )}
            </select>

            {isMicTesting && (
              <div className="mb-3">
                <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
                  <div
                    className="h-3 rounded-full transition-all duration-75"
                    style={{ width: `${Math.round(audioLevel * 100)}%`, backgroundColor: branding?.primary_color ?? '#0d9488' }}
                  />
                </div>
                <p className="text-xs text-gray-400 mt-1">Speak to check audio level</p>
              </div>
            )}

            <button
              onClick={isMicTesting ? stopMicTest : () => testMicrophone(selectedDeviceId || undefined)}
              className="text-sm font-medium text-teal-600 hover:text-teal-700 transition-colors"
            >
              {isMicTesting ? 'Stop test' : 'Test microphone'}
            </button>
          </div>

          <button
            onClick={runInterview}
            className="bg-teal-600 hover:bg-teal-700 text-white font-semibold py-3 px-8 rounded-lg text-lg transition-colors"
            style={{ backgroundColor: branding?.primary_color }}
          >
            Start Interview
          </button>
        </div>
      </div>
    )
  }

  // interviewing
  const interviewerImg = branding?.interviewer_image_url ?? '/agents/avery-singh-hires.jpg'
  const interviewerName = branding?.interviewer_name ?? 'Avery Singh'

  return (
    <div className="h-screen bg-gray-50 flex flex-col">
      {/* Header strip */}
      <div className="bg-white border-b border-gray-100 px-6 py-3 flex items-center gap-4 flex-shrink-0">
        {branding?.header_image_url && (
          <img src={branding.header_image_url} alt="" className="h-8 object-contain" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>Question {progress.current} of {progress.total}</span>
            <span>{Math.round((progress.current / Math.max(progress.total, 1)) * 100)}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-1">
            <div
              className="bg-teal-500 h-1 rounded-full transition-all"
              style={{ width: `${(progress.current / Math.max(progress.total, 1)) * 100}%`, backgroundColor: branding?.primary_color }}
            />
          </div>
        </div>
      </div>

      {/* Main: two-column — photo left, question right */}
      <div className="flex flex-1 min-h-0">
        {/* Interviewer panel */}
        <div className="w-56 flex-shrink-0 bg-slate-900 flex flex-col items-center justify-center gap-5 p-6 border-r border-slate-800">
          <div className="relative">
            <img
              src={interviewerImg}
              alt={interviewerName}
              className="w-40 h-40 rounded-full object-cover ring-4 ring-teal-400 shadow-2xl"
            />
            {(statusMessage || isListening) && (
              <span
                className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-2 border-slate-900 animate-pulse"
                style={{ backgroundColor: branding?.primary_color ?? '#14b8a6' }}
              />
            )}
          </div>
          <div className="text-center">
            <p className="text-white text-sm font-semibold">{interviewerName}</p>
            <p className="text-slate-500 text-[11px] mt-0.5">AI Interviewer</p>
          </div>
        </div>

        {/* Question + controls */}
        <div className="flex-1 flex flex-col items-center justify-center px-10 py-10 gap-8 overflow-y-auto">
          {currentQuestion && (
            <div className="bg-white rounded-2xl shadow-sm px-8 py-7 w-full max-w-xl border border-gray-100">
              <p className="text-gray-800 text-xl leading-relaxed">{currentQuestion}</p>
            </div>
          )}

          <div className="flex flex-col items-center gap-3 w-full max-w-xl">
            {statusMessage && (
              <p className="text-teal-600 font-medium animate-pulse text-sm">{statusMessage}</p>
            )}
            {interimText && (
              <p className="text-sm text-slate-500 italic text-center leading-relaxed px-4">
                &ldquo;{interimText}&rdquo;
              </p>
            )}
            {isListening && (
              <div className="flex items-center gap-3">
                <button
                  onClick={submitAnswer}
                  style={{ backgroundColor: branding?.primary_color }}
                  className="bg-teal-600 hover:bg-teal-700 text-white font-semibold py-3 px-10 rounded-full text-lg transition-colors shadow-md"
                  aria-label="Done speaking"
                >
                  ✓ Done
                </button>
                <button
                  onClick={restartAnswer}
                  className="text-sm text-slate-400 hover:text-slate-600 underline underline-offset-2 transition-colors"
                  aria-label="Restart answer"
                >
                  Restart answer
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
