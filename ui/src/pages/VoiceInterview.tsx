import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { AlertTriangle, Check, Copy, Pause, Play, ShieldCheck, Undo2 } from 'lucide-react'
import type { InterviewSession, InterviewScript, InterviewBranding, MaturityRating, SectionMaturityRating } from '../types'
import {
  browserCanStream,
  deepgramListenUrl,
  fetchDeepgramGrant,
  openDeepgramSocket,
  type Recogniser,
  type RecogniserHooks,
} from '../api/deepgram'

// webkit speech recognition types (Chrome/Safari vendor prefix)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const webkitSpeechRecognition: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const SpeechRecognitionEvent: any

/** Initials for an interviewer with no headshot - a state agents/identity.py declares legitimate. */
function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]!.toUpperCase())
    .join('')
}

type Phase = 'loading' | 'mic_setup' | 'ready' | 'interviewing' | 'rating' | 'complete' | 'error'
type MicStatus = 'no_device' | 'permission_needed' | 'permission_denied' | 'testing' | 'ready'

const BASE = '/api'

// There is deliberately no default voice in this file, and there must never be one again.
//
// `DEFAULT_VOICE_CONFIG` lived here and was a *decision*: `21m00Tcm4TlvDq8ikWAM`, ElevenLabs'
// stock Rachel, a female voice, for an interviewer described as male everywhere he is
// described at all. The first completed interview was conducted in it. It was corrected to a
// mirror of the server's answer, and then deleted, because a session now carries the voice it
// was issued with - so a session arriving without one is a bug, and a fallback here would hide
// it by putting a stranger in front of a participant.
//
// The portal does not send a voice at all now. `POST /interviews/{token}/speak` reads the
// stamp off the session; the only thing this file still takes from `voice_config` is the
// locale it hands the browser's speech recogniser.

export interface CapturedPair {
  question_id: string
  question: string
  answer: string
  follow_up: 0 | 1
}

/**
 * One captured answer, addressed to the question that produced it.
 *
 * qa_pairs used to carry question text alone, so an answer could not be traced to its
 * question even within its own script, and it mixed four different things without
 * distinguishing them: scripted questions, generated probes, pre-scripted branches, and the
 * synthesis block.
 *
 * A follow-up carries its parent's id with a suffix rather than an id of its own. It is
 * further evidence about one question, and counting probes as questions would overstate both
 * coverage and the weight of any theme drawn from them - an interviewee pressed three times
 * on one point would read as three stakeholders' worth of agreement.
 */
export function capturedPair(
  scriptId: string,
  sectionId: string,
  questionNo: number | null,
  question: string,
  answer: string,
  followUp?: { kind: 'F' | 'B'; index: number },
): CapturedPair {
  const base = questionNo === null
    ? `${scriptId}.${sectionId}`
    : `${scriptId}.${sectionId}.Q${questionNo}`
  return {
    question_id: followUp ? `${base}.${followUp.kind}${followUp.index}` : base,
    question,
    answer,
    follow_up: followUp ? 1 : 0,
  }
}

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
  // What has gone wrong with the recogniser, in words a participant can act on. It stays on
  // screen once set: a notice that cleared itself would be gone before somebody mid-sentence
  // looked up, and "nothing you say is being recorded" is precisely the sentence that must not
  // be missed.
  const [recogniserNotice, setRecogniserNotice] = useState('')
  const recognitionRef = useRef<Recogniser | null>(null)
  // One microphone stream for the whole interview, and the two counters that decide whether
  // Deepgram is still worth asking for. `deepgramOffRef` is one-way: once the deployment has
  // shown it has no Deepgram, or a live socket has dropped, every later answer goes straight to
  // the browser's recogniser rather than paying a failed round trip in front of the participant.
  const interviewStreamRef = useRef<MediaStream | null>(null)
  const deepgramFailuresRef = useRef(0)
  const deepgramOffRef = useRef(false)
  const restartAnswerRef = useRef(false)
  // Set by "Finish my last answer". Read inside listenWithRestart, the same way
  // restartAnswerRef is - a flag rather than a callback, because the listen loop owns the
  // recognition object and nothing outside it may drive the microphone.
  const appendToPreviousRef = useRef(false)
  const qaRef = useRef<CapturedPair[]>([])
  const sectionRatingsRef = useRef<SectionMaturityRating[]>([])
  const ratingResolveRef = useRef<((rating: number) => void) | null>(null)
  const interviewLangRef = useRef<string>('en-GB')
  const micStreamRef = useRef<MediaStream | null>(null)
  const micLevelTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [isPaused, setIsPaused] = useState(false)
  const [silenceProgress, setSilenceProgress] = useState(0)
  // The whole pair, not `{question, answer}`. The corrected answers are re-submitted to
  // `/complete` when the participant finishes, and that door requires `question_id` on every
  // pair - narrowing the type here is how an edit would have been sent without its address.
  const [editableTranscript, setEditableTranscript] = useState<CapturedPair[]>([])
  const [savingCorrections, setSavingCorrections] = useState(false)
  const [finished, setFinished] = useState(false)
  const [copied, setCopied] = useState(false)
  const isPausedRef = useRef(false)
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const silenceIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const resetSilenceTimerRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    fetchSession()
  }, [sessionToken])

  // Stop mic test stream when leaving mic_setup or ready phase
  useEffect(() => {
    if (phase !== 'mic_setup' && phase !== 'ready') stopMicTest()
  }, [phase])

  // Release the interview's own microphone stream when the interview is over, and on unmount.
  // It is held open for the whole interview on purpose - see interviewStream - so nothing else
  // releases it, and a stream left running keeps the browser's recording indicator lit on a
  // page that has finished asking questions.
  useEffect(() => {
    if (phase === 'complete' || phase === 'error') releaseInterviewStream()
  }, [phase])
  useEffect(() => releaseInterviewStream, [])

  // Snapshot the QA ref into editable state when the interview completes
  useEffect(() => {
    if (phase === 'complete') setEditableTranscript([...qaRef.current])
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
      // Peer referral and the closing message are steps the participant still has to sit
      // through, so they count. Without them the bar read 100% on the last scripted
      // question while follow-ups, the referral and the closing were all still to come -
      // which is the moment a participant decides how much longer this will take.
      //
      // Follow-ups are deliberately NOT in the denominator: there are nought to two per
      // question, decided live, so any fixed guess is wrong in both directions. The bar
      // therefore advances a little slower than the work remaining, and never overstates
      // completion, which is the failure that matters.
      const TRAILING_STEPS = 2
      const total = data.script.sections.reduce(
        (acc: number, s: { questions: unknown[] }) => acc + s.questions.length,
        0
      ) + TRAILING_STEPS
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

  async function speakText(text: string): Promise<void> {
    setStatusMessage('Speaking…')
    const res = await fetch(`${BASE}/interviews/${sessionToken}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
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

  /**
   * The browser's own recogniser, which is the fallback rather than the first choice.
   *
   * Unchanged in behaviour, including Chrome's habit of stopping the recogniser on its own
   * timer - `onend` restarts it unless the stop was ours. That sentinel used to be
   * `recognitionRef.current === recognition`, a piece of the page's state read from inside the
   * engine; it is a local flag now, because there are two engines and only one ref.
   */
  function startWebSpeech(lang: string, hooks: RecogniserHooks): Recogniser | null {
    const SpeechRecognition =
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).SpeechRecognition ||
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) return null

    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = lang
    let stopping = false

    recognition.onresult = (event: typeof SpeechRecognitionEvent) => {
      hooks.onSpeechActivity()
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) hooks.onFinal(event.results[i][0].transcript)
      }
      const interim = Array.from(event.results as unknown[])
        .slice(event.resultIndex)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .filter((r: any) => !r.isFinal)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .map((r: any) => r[0].transcript)
        .join(' ')
      if (interim) hooks.onInterim(interim)
    }

    recognition.onend = () => {
      if (!stopping) {
        try {
          recognition.start()
          return
        } catch {
          // Cannot restart - permission revoked mid-session, or the engine is gone.
        }
      }
      hooks.onClosed()
    }

    recognition.onerror = (event: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
      // Whatever the error, do not restart: let onend close the answer out.
      stopping = true
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        hooks.onDropped('microphone')
      }
    }

    recognition.start()
    return { stop: () => { stopping = true; try { recognition.stop() } catch { hooks.onClosed() } } }
  }

  /**
   * The microphone stream the interview records from, acquired once and kept.
   *
   * One stream for the whole interview rather than one per question: `getUserMedia` per answer
   * makes the browser's recording indicator flicker on and off between every question, which
   * reads to a participant as something going wrong.
   */
  function releaseInterviewStream() {
    interviewStreamRef.current?.getTracks().forEach(track => track.stop())
    interviewStreamRef.current = null
  }

  async function interviewStream(): Promise<MediaStream | null> {
    if (interviewStreamRef.current) return interviewStreamRef.current
    if (!navigator.mediaDevices?.getUserMedia) return null
    try {
      const audio: MediaTrackConstraints | boolean = selectedDeviceId
        ? { deviceId: { exact: selectedDeviceId } }
        : true
      const stream = await navigator.mediaDevices.getUserMedia({ audio, video: false })
      interviewStreamRef.current = stream
      return stream
    } catch {
      return null
    }
  }

  /**
   * Deepgram, told this project's own words - and `null` for every reason it cannot be reached.
   *
   * Each of those reasons means the same thing to the caller (use the browser's recogniser), so
   * they are not distinguished here. What *is* counted is how many times in a row it has
   * happened: a transient failure on the first question must not condemn the rest of the
   * interview to a recogniser that has never heard of the client, and a deployment with no
   * Deepgram key must not pay a failed round trip before every single answer.
   */
  async function startDeepgram(hooks: RecogniserHooks): Promise<Recogniser | null> {
    if (deepgramOffRef.current || !browserCanStream()) return null
    const grant = await fetchDeepgramGrant(BASE, sessionToken ?? '')
    if (!grant) return null
    const stream = await interviewStream()
    if (!stream) return null
    return openDeepgramSocket(stream, deepgramListenUrl(grant), hooks)
  }

  /**
   * Listen for one answer, on whichever recogniser can be had.
   *
   * Deepgram first, because it is the only one that has been told what this engagement calls
   * things; the browser's recogniser second, because it needs no key and no network of ours;
   * and if neither can listen, **the participant is told in plain words rather than left
   * speaking into nothing**. The silence countdown starts when a recogniser is actually
   * listening, not when this function is entered - fetching a grant and opening a socket takes
   * a second or two, and counting that against a participant's thinking time would move the
   * interview on before they had been heard at all.
   */
  function listenForAnswer(lang: string = 'en-GB'): Promise<string> {
    return new Promise((resolve) => {
      const parts: string[] = []
      let resolved = false
      let engine: Recogniser | null = null
      let stopRequested = false

      // Longer initial wait (before first speech), shorter gap once they've started
      const INITIAL_SILENCE_MS = 10000
      const ANSWER_SILENCE_MS  = 3000
      const TICK_MS = 50

      function clearSilenceTimers() {
        if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null }
        if (silenceIntervalRef.current) { clearInterval(silenceIntervalRef.current); silenceIntervalRef.current = null }
      }

      function finish() {
        if (resolved) return
        resolved = true
        recognitionRef.current = null
        clearSilenceTimers()
        setSilenceProgress(0)
        setIsListening(false)
        setStatusMessage('')
        setInterimText('')
        resolve(parts.join(' ').trim())
      }

      function resetSilenceTimer(initial = false) {
        if (isPausedRef.current || resolved) return
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
          recognitionRef.current = null
          handle.stop()
        }, duration)
      }

      // The buttons need something to stop from the first frame, before any engine exists -
      // "Done", "Restart answer" and the silence timer can all fire while a socket is still
      // being opened, and a stop that reached nothing would hang the interview on that question.
      const handle: Recogniser = {
        stop: () => {
          stopRequested = true
          if (engine) engine.stop()
          else finish()
        },
      }
      recognitionRef.current = handle

      const hooks: RecogniserHooks = {
        onSpeechActivity: () => resetSilenceTimer(false),
        onFinal: (text) => { if (text) parts.push(text) },
        onInterim: (text) => setInterimText([...parts, text].join(' ').trim()),
        onClosed: finish,
        onDropped: (reason) => {
          if (resolved) return
          if (reason === 'microphone') {
            // The browser's recogniser has lost the microphone, and so would any other. There
            // is nothing to hand over to; onClosed follows and ends the answer.
            setRecogniserNotice(
              'We have lost access to your microphone. Allow microphone access for this page, ' +
              'then use Done to carry on.',
            )
            return
          }
          // The socket dropped mid-answer. The participant is still talking, so the worst
          // possible response is to end the answer quietly and let them finish into nothing.
          // Hand the rest of this same answer to the browser's recogniser, keep what was
          // already heard, and say what happened - both halves, not either.
          deepgramOffRef.current = true
          setRecogniserNotice(
            'The transcription service dropped out. What you have said so far has been kept, ' +
            'and the interview is carrying on using your browser to transcribe. Please continue.',
          )
          engine = startWebSpeech(lang, hooks)
          if (!engine) finish()
        },
      }

      setStatusMessage('Listening…')
      setIsListening(true)
      setIsPaused(false)
      isPausedRef.current = false
      setSilenceProgress(0)
      resetSilenceTimerRef.current = () => resetSilenceTimer(false)

      void (async () => {
        engine = await startDeepgram(hooks)
        if (!engine) {
          deepgramFailuresRef.current += 1
          // Two in a row is a deployment without Deepgram, not a bad moment. Stop asking: a
          // failed round trip before every answer is latency a participant sits through.
          if (deepgramFailuresRef.current >= 2) deepgramOffRef.current = true
          engine = startWebSpeech(lang, hooks)
        } else {
          deepgramFailuresRef.current = 0
        }

        if (!engine) {
          // Nothing in this browser can listen. Say so - an interview that carries on silently
          // records nothing and tells the participant afterwards, which is the worst outcome
          // available to a person who has given up an hour.
          setRecogniserNotice(
            'This browser cannot transcribe speech, so nothing you say is being recorded. ' +
            'Please reopen your interview link in Chrome or Edge, or contact the person who invited you.',
          )
          finish()
          return
        }

        if (stopRequested) {
          engine.stop()
          return
        }
        // The countdown starts now that something is actually listening.
        resetSilenceTimer(true)
      })()
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

  /**
   * "Finish my last answer" - continuation, not navigation.
   *
   * Twice in the first completed interview a participant paused mid-reply, the three-second
   * gap elapsed, and the interview moved on with the thought unfinished and no way back.
   *
   * This does not go back. The interview is an await loop over sections and questions, so
   * going back means unwinding an await, which needs the whole engine restructured into an
   * index-driven state machine - a large change to a working thing, for a capability nobody
   * asked for. True back navigation also has to decide what happens to the answer already
   * given (overwrite, keep both, discard), and every choice loses something.
   *
   * What was actually wanted was to finish a sentence. So the next thing said is appended to
   * the previous answer, and the current question is then re-asked. The transcript ends up
   * with one complete answer per question rather than a fragment and an orphan - which
   * matters downstream, where a truncated answer can also read as evasive and provoke a
   * press the participant never warranted.
   */
  function finishLastAnswer() {
    appendToPreviousRef.current = true
    submitAnswer()
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

  /**
   * Listen for an answer, re-prompting once if nothing was said.
   *
   * `listenForAnswer` resolves `''` after ten seconds of no speech, and the flow used to
   * take that as an answer and advance. A participant who paused to think, or whose
   * microphone picked up only room noise, lost the question without being told - which is
   * what happened in the first completed interview.
   *
   * One re-prompt, then move on. Not unlimited: a participant who has walked away must not
   * trap the interview in a loop, and repeating a third time reads as nagging rather than
   * patience. `reprompt` is spoken only when the caller supplies it, so a caller with
   * nothing sensible to repeat simply gets the old behaviour.
   */
  async function listenWithRestart(
    lang: string = 'en-GB',
    reprompt?: { text: string },
  ): Promise<string> {
    restartAnswerRef.current = false
    appendToPreviousRef.current = false
    let silentAttempts = 0
    // Anything already said for THIS question before "Finish my last answer" was tapped.
    // Carried rather than discarded: the participant is correcting the previous answer, not
    // retracting this one, and losing words they have already spoken is the same failure the
    // button exists to fix.
    let carried = ''
    // eslint-disable-next-line no-constant-condition
    while (true) {
      setInterimText('')
      const heard = await listenForAnswer(lang)

      if (restartAnswerRef.current) {
        restartAnswerRef.current = false
        carried = ''
        setStatusMessage('Restarting…')
        await new Promise(r => setTimeout(r, 300))
        setStatusMessage('')
        continue
      }

      if (appendToPreviousRef.current) {
        appendToPreviousRef.current = false
        carried = [carried, heard].filter(Boolean).join(' ').trim()
        const previous = qaRef.current[qaRef.current.length - 1]
        if (!previous) {
          // Nothing has been committed yet, so there is nothing to finish. Say so rather
          // than silently doing nothing, and carry on with the current question.
          setStatusMessage('There is no earlier answer to add to yet.')
          await new Promise(r => setTimeout(r, 1500))
          setStatusMessage('')
          continue
        }
        setStatusMessage('Go ahead — finish your last answer.')
        if (reprompt) await speakText('Of course — go on.')
        const extra = await listenForAnswer(lang)
        setStatusMessage('')
        if (extra.trim()) previous.answer = `${previous.answer} ${extra}`.trim()
        // Back to where we were.
        if (reprompt) {
          setCurrentQuestion(reprompt.text)
          await speakText(reprompt.text)
        }
        continue
      }

      const answer = [carried, heard].filter(Boolean).join(' ').trim()

      // Nothing heard. Ask once more before giving up on this question.
      if (answer.length === 0 && reprompt && silentAttempts === 0) {
        silentAttempts++
        setStatusMessage('')
        await speakText("Sorry — I didn't catch that. Let me ask again.")
        setCurrentQuestion(reprompt.text)
        await speakText(reprompt.text)
        continue
      }

      return answer
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
      // An empty press_text is the server reporting that the press went over its budget and
      // produced nothing - it is an answer, not a missing field, so it is returned as-is for
      // the caller to skip on. `??` treated "" as present and passed it straight through to
      // speakText and setCurrentQuestion, which left the interviewee recording in silence in
      // front of a blank question and wrote an answer row with no question text. That fires
      // most often in secure mode, where the local model is slowest - so the budget made the
      // sensitive-project interview worse than having no budget at all.
      return typeof data.press_text === 'string' ? data.press_text : "Could you tell me more about that?"
    } catch {
      return "Could you tell me more about that?"
    }
  }

  /**
   * Submit the transcript to `/complete`. Called twice for one interview: once when the
   * closing message has been spoken, and again when the participant finishes the review step,
   * carrying whatever they corrected.
   *
   * One function rather than two calls, because the second submission has to restate things
   * it has no opinion about. `complete_interview_session` writes `ratings_json` unconditionally,
   * so a resubmission that omitted the ratings would set them to NULL and silently discard
   * every maturity rating the interview collected - the transcript would be corrected and the
   * ratings lost, with a 200 either way.
   *
   * Resubmitting is safe by design rather than by luck: `insert_interview_answer` upserts on
   * `(session_id, question_id)` and re-indexes from the row ids it returns, so a corrected
   * answer replaces the stored one under the id retrieved chunks already cite.
   */
  async function postCompletion(pairs: CapturedPair[], ratings: SectionMaturityRating[]) {
    try {
      const res = await fetch(`${BASE}/interviews/${sessionToken}/complete`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          qa_pairs: pairs,
          ratings: ratings.length > 0 ? ratings : undefined,
        }),
      })
      if (!res.ok) console.warn('complete endpoint returned', res.status)
    } catch (err) {
      console.error('Failed to submit responses', err)
    }
  }

  async function submitResponses(ratings: SectionMaturityRating[]) {
    setStatusMessage('Saving your responses…')
    await postCompletion(qaRef.current, ratings)
    setPhase('complete')
    setStatusMessage('')
    setCurrentQuestion('')
  }

  async function runInterview() {
    if (!sessionData) return
    const { session, script } = sessionData
    // The session is stamped with its interviewer's resolved configuration when it is created.
    // A session without one cannot be conducted, and saying so is the point: the alternative -
    // a default declared here - is what conducted the first completed interview in a voice
    // nobody had chosen. The speak door refuses the same case for the same reason.
    const voiceConfig = session.voice_config
    if (!voiceConfig?.elevenlabs_voice_id) {
      setErrorMessage(
        'This interview session was created without a voice, so it cannot be conducted. ' +
        'Please contact the person who invited you.',
      )
      setPhase('error')
      return
    }
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
    await speakText(script.welcome_message)

    // Framing block (L2 only) — spoken after welcome, before first question
    if (script.framing_block) {
      const fb = script.framing_block
      // Positioning only. The block previously spoke positioning, every context_setting
      // bullet and both dual_lenses joined into one utterance - around a minute of
      // preamble after a welcome that had already covered purpose and confidentiality.
      // The rest stays in the script for the reader and the analyst; it is not read aloud.
      setCurrentQuestion(fb.positioning)
      await speakText(fb.positioning)
    }

    let questionNumber = 0

    sectionRatingsRef.current = []

    const scriptId = script.script_id ?? ''

    for (const [sectionIndex, section] of script.sections.entries()) {
      // Falls back to position when a script predates section ids, so an older script still
      // produces addressable answers rather than colliding every section onto one id.
      const sectionId = section.section_id ?? `S${sectionIndex + 1}`
      for (const [questionIndex, question] of section.questions.entries()) {
        const questionNo = questionIndex + 1
        questionNumber++
        setProgress(p => ({ ...p, current: questionNumber }))
        setCurrentQuestion(question.text)

        // Ask the question
        await speakText(question.text)

        // Record primary answer
        let answer = await listenWithRestart(lang, { text: question.text })

        const needsElaboration =
          answer.trim().length > 0 &&
          question.evasion_signals.some(sig => answer.toLowerCase().includes(sig.toLowerCase()))

        let followUpCount = 0

        if (needsElaboration) {
          // Press for elaboration. An empty press means no press was produced in time, so
          // the whole branch is skipped and the interview moves on to the next question -
          // a missed follow-up costs depth on one answer, while speaking nothing and then
          // listening costs the interviewee's confidence in the whole conversation.
          const pressText = await getElaborationPress(question.text, answer, question.probing_instructions)
          if (pressText) {
            setCurrentQuestion(pressText)
            await speakText(pressText)
            const followUpAnswer = await listenWithRestart(lang)
            qaRef.current.push(capturedPair(scriptId, sectionId, questionNo, pressText, followUpAnswer, { kind: 'F', index: followUpCount + 1 }))
            answer = `${answer} ${followUpAnswer}`.trim()
            followUpCount++
          }
        }

        // Push primary Q&A before follow-up branches
        qaRef.current.push(capturedPair(scriptId, sectionId, questionNo, question.text, answer))

        // Pre-scripted follow-up branches
        while (followUpCount < question.follow_up_count && question.follow_up_branches[followUpCount]) {
          const branch = question.follow_up_branches[followUpCount]
          setCurrentQuestion(branch)
          await speakText(branch)
          const branchAnswer = await listenWithRestart(lang)
          qaRef.current.push(capturedPair(scriptId, sectionId, questionNo, branch, branchAnswer, { kind: 'B', index: followUpCount + 1 }))
          followUpCount++
        }
      }

      // After all questions in a section, capture inline maturity rating if present (L1/L2 only)
      if (section.maturity_rating) {
        const mr = section.maturity_rating
        await speakText(mr.prompt)
        const rating = await collectInlineRating(mr)
        sectionRatingsRef.current.push({ section_title: section.title, dimension: mr.dimension, rating })
        setPhase('interviewing')
      }
    }

    // SYNTHESIS WITHDRAWN — 4 September 2026, until further notice.
    //
    // Everything below except peer referral is commented out rather than deleted, on
    // Patrick's instruction, after the first completed interview.
    //
    // Two findings, and the second is the sharper one:
    //
    //  - `synthesis_prompt` is written by Maya at design time, so the interviewer read a
    //    summary of the conversation composed before anybody had said anything. A synthesis
    //    check has to be a check of what was actually said.
    //
    //  - `portfolio_options` did the same for the recommendation. It offered three sequencing
    //    options - sequential, parallel, phased - to a participant who had already said the
    //    projects must run in parallel. It was assumed at the time to be dynamic synthesis
    //    going wrong; it is not. Nothing here generates anything. The script pre-supposed the
    //    answer, which is worse, because it is repeatable.
    //
    // The general rule this leaves: anything an agent says TO a participant in real time has
    // no reviewer between it and them, so it is either scripted and true, or absent.
    //
    // Peer referral survives because it asks a question rather than asserting a conclusion.
    //
    // Restoring any of this needs the Maya-side change too: the fields stay in the script
    // schema for now, and are dropped from questionnaire design later.
    if (script.synthesis_check) {
      const sc = script.synthesis_check
      // WITHDRAWN: scripted synthesis check.
      // setCurrentQuestion(sc.synthesis_prompt)
      // await speakText(sc.synthesis_prompt)
      // const synthesisResponse = await listenWithRestart(lang)
      // qaRef.current.push(capturedPair(scriptId, 'SYNTH', 1, sc.synthesis_prompt, synthesisResponse))

      // Peer referral - retained. It asks who else to speak to; it asserts nothing.
      setProgress(p => ({ ...p, current: p.current + 1 }))
      setCurrentQuestion(sc.peer_referral)
      await speakText(sc.peer_referral)
      const referralResponse = await listenWithRestart(lang)
      qaRef.current.push(capturedPair(scriptId, 'SYNTH', 2, sc.peer_referral, referralResponse))

      // WITHDRAWN: forward roadmap.
      // setCurrentQuestion(sc.forward_roadmap)
      // await speakText(sc.forward_roadmap)
      // const roadmapResponse = await listenWithRestart(lang)
      // qaRef.current.push(capturedPair(scriptId, 'SYNTH', 3, sc.forward_roadmap, roadmapResponse))

      // WITHDRAWN: portfolio sequencing options - the field that offered a participant
      // options they had already ruled out.
      // if (sc.portfolio_options) { ... }

      // WITHDRAWN: sponsorship commitment check.
      // if (sc.sponsorship_check) { ... }
    }

    // Closing. The bar reaches 100% here and nowhere earlier.
    setProgress(p => ({ ...p, current: p.total }))
    setCurrentQuestion(script.closing_message)
    await speakText(script.closing_message)

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

  /** The transcript as a participant would paste it - the text the Copy button puts on the
   *  clipboard, built from what is in the fields now rather than from what was recorded. */
  function transcriptAsText(): string {
    return editableTranscript.map(pair => `${pair.question}\n${pair.answer}`).join('\n\n')
  }

  async function handleCopyTranscript() {
    try {
      await navigator.clipboard?.writeText(transcriptAsText())
      setCopied(true)
    } catch {
      // A browser that refuses clipboard access leaves the button saying "Copy" rather than
      // claiming a copy that did not happen. The whole point of this screen is that it stopped
      // telling a participant something had worked when it had not.
      setCopied(false)
    }
  }

  /**
   * Finishing the review submits the corrections.
   *
   * Nothing is emailed. The checkbox that used to sit here posted to `/email-transcript`,
   * which answered `{"sent": true}` to a participant who never received anything: `dev_mode`
   * holds project mail and `FROM_EMAIL` names a domain Resend has not verified. It was the one
   * path in the product where the person who triggered the action was told it had worked.
   *
   * What that post also did, incidentally, was carry the corrected answers - so it was the only
   * route an edit had to the server, and only for a participant who happened to tick a box.
   * Everyone else corrected their transcript into a state variable that was then discarded.
   * The corrections now go to `/complete`, which is where the transcript lives.
   */
  async function handleFinishInterview() {
    setSavingCorrections(true)
    await postCompletion(editableTranscript, sectionRatingsRef.current)
    setSavingCorrections(false)
    setFinished(true)
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
    const primaryColor = branding?.primary_color ?? '#0d9488'
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col">
        {branding?.header_image_url && (
          <div className="bg-white border-b border-gray-100 px-6 py-3 flex-shrink-0">
            <img src={branding.header_image_url} alt="" className="h-10 object-contain" />
          </div>
        )}
        <div className="flex-1 overflow-y-auto px-4 py-8">
          <div className="max-w-2xl mx-auto">
            <div className="text-center mb-8">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-teal-50 mb-3">
                <Check size={24} style={{ color: primaryColor }} />
              </div>
              <h1 className="text-2xl font-bold text-gray-800">Thank you!</h1>
              <p className="text-gray-500 text-sm mt-1">
                {finished
                  ? 'Your responses have been recorded. You may now close this window.'
                  : 'Please review your responses below. Every answer can be edited - correct anything the recogniser misheard before you finish.'}
              </p>
            </div>

            {!finished && (
              <>
                <div className="space-y-4 mb-6">
                  {editableTranscript.map((pair, i) => (
                    <div key={pair.question_id || i} className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                      <div className="px-4 py-3 bg-gray-50 border-b border-gray-100">
                        <p id={`review-question-${i}`} className="text-sm text-gray-600 leading-relaxed">
                          {pair.question}
                        </p>
                      </div>
                      <div className="px-4 py-3">
                        {/* Open, always. This was a `text-gray-300` pencil that had to be found
                            and hovered before an answer could be corrected, on a screen carrying
                            59 of them in the 4 September walkthrough - and correcting what the
                            recogniser heard is the last chance anybody gets. An affordance
                            nobody notices is not an affordance.

                            The question is the field's *description*, not its name: an implicit
                            <label> wrapping both would give every field a different accessible
                            name, so "offer every answer for editing" could only be asserted by
                            counting nodes rather than by asking for the control. */}
                        <textarea
                          aria-label="Your answer"
                          aria-describedby={`review-question-${i}`}
                          className="w-full text-sm text-gray-700 border border-gray-200 rounded-lg p-2.5 resize-y focus:outline-none focus:ring-2 focus:ring-teal-400"
                          rows={4}
                          value={pair.answer}
                          placeholder="No response recorded"
                          onChange={e => {
                            const corrected = e.target.value
                            setEditableTranscript(current =>
                              current.map((p, idx) => (idx === i ? { ...p, answer: corrected } : p)),
                            )
                            // What is on the clipboard is no longer this transcript.
                            setCopied(false)
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>

                <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 mb-6">
                  <div className="flex items-start gap-3">
                    <ShieldCheck size={18} className="flex-shrink-0 mt-0.5 text-gray-400" />
                    <div className="flex-1">
                      {/* The note that replaced "Send a copy of this transcript to me". That
                          checkbox posted to /email-transcript, which answered {"sent": true}
                          and delivered nothing. Nothing here promises a message. */}
                      <p className="text-sm text-gray-700">
                        For confidentiality, this transcript is not emailed to anyone. If you
                        would like your own copy, use the Copy button below and paste it
                        wherever you keep it.
                      </p>
                      <button
                        type="button"
                        onClick={handleCopyTranscript}
                        className="mt-3 inline-flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-800 border border-gray-200 rounded-lg px-3 py-2 transition-colors"
                      >
                        <Copy size={14} />{copied ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="text-center">
                  <button
                    onClick={handleFinishInterview}
                    disabled={savingCorrections}
                    className="px-8 py-3 rounded-xl text-white font-medium text-sm disabled:opacity-50 transition-opacity"
                    style={{ backgroundColor: primaryColor }}
                  >
                    {savingCorrections ? 'Saving…' : 'Finish'}
                  </button>
                </div>
              </>
            )}
          </div>
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

          {/* Interviewer persona. Keyed on the NAME, not the photograph: the server resolves
              both from the session's stamp, and an interviewer without a headshot is a
              legitimate state that agents/identity.py has always allowed. Keying this block on
              the image hid the name of the only interviewer who is actually in that state. */}
          {branding?.interviewer_name && (
            <div className="flex flex-col items-center mb-6">
              {branding.interviewer_image_url ? (
                <img
                  src={branding.interviewer_image_url}
                  alt={branding.interviewer_name}
                  className="w-24 h-24 rounded-full object-cover shadow-md mb-3 ring-4 ring-white"
                />
              ) : (
                <div
                  className="w-24 h-24 rounded-full mb-3 ring-4 ring-white shadow-md flex items-center justify-center text-2xl font-semibold text-white bg-gradient-to-br from-slate-500 to-slate-700"
                  aria-hidden="true"
                >
                  {initialsOf(branding.interviewer_name)}
                </div>
              )}
              <p className="font-semibold text-gray-800" style={{ color: branding.text_color }}>
                {branding.interviewer_name}
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
                'Once you have answered, a pause of a few seconds - or tapping “✓ Done” - moves on.',
                'Need a moment to think? Tap “Hold — I\'m thinking” to pause the timer.',
                'Tap “Restart answer” at any time to re-record your response.',
                'Cut off mid-thought? “Finish my last answer” adds to your previous reply.',
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

  // interviewing.
  //
  // No literal name and no literal photograph. Both used to be declared here - "Avery Singh"
  // and /agents/avery-singh-hires.jpg - which were the third and fourth declarations of the
  // interviewer's identity in the product, and they were what a participant read while Laura
  // was speaking to them. The server resolves both from the session's stamp.
  const interviewerImg = branding?.interviewer_image_url ?? ''
  const interviewerName = branding?.interviewer_name ?? ''

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
            {interviewerImg ? (
              <img
                src={interviewerImg}
                alt={interviewerName}
                className="w-40 h-40 rounded-full object-cover ring-4 ring-teal-400 shadow-2xl"
              />
            ) : (
              <div
                className="w-40 h-40 rounded-full ring-4 ring-teal-400 shadow-2xl flex items-center justify-center text-4xl font-semibold text-white bg-gradient-to-br from-slate-600 to-slate-800"
                aria-hidden="true"
              >
                {initialsOf(interviewerName)}
              </div>
            )}
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
            {/* Whatever has gone wrong with the recogniser, said plainly and left on screen.
                A participant mid-interview cannot diagnose a dropped socket or a browser with
                no speech API, and the one thing they must never be is unaware of it. */}
            {recogniserNotice && (
              <div
                // `alert`, not `status`. One of the sentences this carries is "nothing you say
                // is being recorded", and a polite live region may wait for a pause that a
                // participant mid-interview never gives it. Assertive is right when the notice
                // is the reason to stop talking.
                role="alert"
                data-testid="recogniser-notice"
                className="flex items-start gap-2 w-full rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
              >
                <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span>{recogniserNotice}</span>
              </div>
            )}
            {statusMessage && (
              <p className="text-teal-600 font-medium animate-pulse text-sm">{statusMessage}</p>
            )}
            {interimText && (
              <p className="text-sm text-slate-500 italic text-center leading-relaxed px-4">
                &ldquo;{interimText}&rdquo;
              </p>
            )}
            {isListening && (
              <div className="flex flex-col items-center gap-3 w-full max-w-sm">
                {/* Silence countdown bar */}
                {!isPaused && (
                  <div className="w-full">
                    <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="h-1.5 rounded-full transition-none"
                        style={{ width: `${silenceProgress}%`, backgroundColor: branding?.primary_color ?? '#0d9488' }}
                      />
                    </div>
                    <p className="text-[11px] text-gray-400 text-center mt-1">
                      {silenceProgress > 0 ? 'Moving on when you stop speaking…' : 'Waiting for your response…'}
                    </p>
                  </div>
                )}
                {isPaused && (
                  <p className="text-sm text-amber-600 font-medium">Interview paused — take your time.</p>
                )}
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
                  {/* Only offered once there is an earlier answer to add to. */}
                  {qaRef.current.length > 0 && (
                    <button
                      onClick={finishLastAnswer}
                      className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-600 underline underline-offset-2 transition-colors"
                      aria-label="Finish my last answer"
                    >
                      <Undo2 size={14} />Finish my last answer
                    </button>
                  )}
                </div>
                {/* Pause / Resume thinking time */}
                {isPaused ? (
                  <button
                    onClick={handleResume}
                    className="flex items-center gap-2 text-sm font-medium text-teal-700 bg-teal-50 hover:bg-teal-100 border border-teal-200 rounded-full px-4 py-2 transition-colors"
                    aria-label="Resume - I'm good, let's continue"
                  >
                    <Play size={14} />Ready — continue
                  </button>
                ) : (
                  <button
                    onClick={handlePause}
                    className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-full px-4 py-2 transition-colors"
                    aria-label="Pause - I need a moment to think"
                  >
                    <Pause size={14} />Hold — I'm thinking
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
