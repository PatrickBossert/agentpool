import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import type { InterviewSession, InterviewScript, InterviewBranding, QuestionnaireTemplateSchema, SectionRatings } from '../types'

// webkit speech recognition types (Chrome/Safari vendor prefix)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const webkitSpeechRecognition: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const SpeechRecognitionEvent: any

type Phase = 'loading' | 'mic_setup' | 'ready' | 'interviewing' | 'assessing' | 'complete' | 'error'
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
  const [questionnaire, setQuestionnaire] = useState<QuestionnaireTemplateSchema | null>(null)
  const [, setSectionRatings] = useState<SectionRatings[]>([])
  const [currentAssessSection, setCurrentAssessSection] = useState(0)
  const [pendingRatings, setPendingRatings] = useState<Record<string, number>>({})
  const [micStatus, setMicStatus] = useState<MicStatus>('no_device')
  const [audioLevel, setAudioLevel] = useState(0)
  const [availableDevices, setAvailableDevices] = useState<MediaDeviceInfo[]>([])
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('')
  const [isMicTesting, setIsMicTesting] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null)
  const qaRef = useRef<{ question: string; answer: string }[]>([])
  const sectionRatingsRef = useRef<SectionRatings[]>([])
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
      if (data.questionnaire) setQuestionnaire(data.questionnaire)

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

  async function submitResponses(ratings: SectionRatings[]) {
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

    for (const section of script.sections) {
      for (const question of section.questions) {
        questionNumber++
        setProgress(p => ({ ...p, current: questionNumber }))
        setCurrentQuestion(question.text)

        // Ask the question
        await speakText(question.text, voiceId)

        // Record primary answer
        let answer = await listenForAnswer(lang)

        const needsElaboration =
          answer.trim().length > 0 &&
          question.evasion_signals.some(sig => answer.toLowerCase().includes(sig.toLowerCase()))

        let followUpCount = 0

        if (needsElaboration) {
          // Press for elaboration
          const pressText = await getElaborationPress(question.text, answer, question.probing_instructions)
          setCurrentQuestion(pressText)
          await speakText(pressText, voiceId)
          const followUpAnswer = await listenForAnswer(lang)
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
          const branchAnswer = await listenForAnswer(lang)
          qaRef.current.push({ question: branch, answer: branchAnswer })
          followUpCount++
        }
      }
    }

    // Closing
    setCurrentQuestion(script.closing_message)
    await speakText(script.closing_message, voiceId)

    if (questionnaire) {
      setPhase('assessing')
      setCurrentAssessSection(0)
      setPendingRatings({})
      sectionRatingsRef.current = []
      return  // assessment phase will call submitResponses when done
    }
    // else submit directly with no ratings
    await submitResponses([])
  }

  async function startCommentary() {
    if (sessionData && questionnaire) {
      const { session } = sessionData
      const voiceId = (session.voice_config ?? DEFAULT_VOICE_CONFIG).elevenlabs_voice_id
      const section = questionnaire.sections[currentAssessSection]
      await speakText(`Any additional commentary on ${section.title}?`, voiceId)
    }
    const commentary = await listenForAnswer()
    advanceSection(commentary)
  }

  function advanceSection(commentary: string) {
    if (!questionnaire) return
    const section = questionnaire.sections[currentAssessSection]
    const completed: SectionRatings = {
      section_id: section.id,
      section_title: section.title,
      ratings: { ...pendingRatings },
      commentary,
    }
    sectionRatingsRef.current = [...sectionRatingsRef.current, completed]
    setSectionRatings(sectionRatingsRef.current)

    if (currentAssessSection + 1 < questionnaire.sections.length) {
      setCurrentAssessSection(i => i + 1)
      setPendingRatings({})
    } else {
      submitResponses(sectionRatingsRef.current)
    }
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

  if (phase === 'assessing' && questionnaire) {
    const section = questionnaire.sections[currentAssessSection]
    const allRated = section.questions.every(q => pendingRatings[q.id] !== undefined)

    return (
      <div className="h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
        <div className="max-w-2xl w-full">
          {branding?.header_image_url && (
            <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
          )}
          <div className="mb-6">
            <p className="text-xs text-teal-600 font-medium uppercase tracking-wide mb-1">
              Assessment · Section {currentAssessSection + 1} of {questionnaire.sections.length}
            </p>
            <h2 className="text-xl font-bold text-gray-800">{section.title}</h2>
            {section.description && (
              <p className="text-sm text-gray-500 mt-1">{section.description}</p>
            )}
          </div>

          <div className="space-y-6 mb-8">
            {section.questions.map(q => (
              <div key={q.id} className="bg-white rounded-xl shadow-sm p-5">
                <p className="text-gray-800 mb-3">{q.text}</p>
                <div className="flex gap-2">
                  {[0, 1, 2, 3, 4].map(score => (
                    <button
                      key={score}
                      onClick={() => setPendingRatings(r => ({ ...r, [q.id]: score }))}
                      aria-label={`Score ${score} for: ${q.text}`}
                      className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                        pendingRatings[q.id] === score
                          ? 'bg-teal-600 text-white border-teal-600'
                          : 'bg-white text-gray-600 border-gray-200 hover:border-teal-400'
                      }`}
                    >
                      {score}
                    </button>
                  ))}
                </div>
                <div className="flex justify-between text-xs text-gray-400 mt-1 px-1">
                  <span>Not Accounted For</span>
                  <span>Optimised</span>
                </div>
              </div>
            ))}
          </div>

          {allRated ? (
            <div className="bg-white rounded-xl shadow-sm p-5 mb-6">
              <p className="text-sm font-medium text-gray-700 mb-3">
                Any additional commentary for this section? (speak or skip)
              </p>
              {statusMessage && (
                <p className="text-teal-600 text-sm animate-pulse mb-2">{statusMessage}</p>
              )}
              <div className="flex gap-3">
                {!isListening ? (
                  <button
                    onClick={startCommentary}
                    className="bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium py-2 px-4 rounded-lg transition-colors"
                    style={{ backgroundColor: branding?.primary_color }}
                  >
                    Speak
                  </button>
                ) : (
                  <button
                    onClick={submitAnswer}
                    className="bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium py-2 px-4 rounded-full transition-colors"
                    style={{ backgroundColor: branding?.primary_color }}
                  >
                    ✓ Done
                  </button>
                )}
                <button
                  onClick={() => advanceSection('')}
                  disabled={isListening}
                  className="text-sm text-gray-400 hover:text-gray-600 py-2 px-4 disabled:opacity-40"
                >
                  Skip
                </button>
              </div>
            </div>
          ) : (
            <p className="text-xs text-gray-400 text-center mb-6">
              Please rate all statements above to continue.
            </p>
          )}
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

          <h1 className="text-2xl font-bold text-gray-800 mb-2" style={{ color: branding?.text_color }}>
            {sessionData.script.node_label} Interview
          </h1>
          <p className="text-gray-500 mb-6 text-sm">
            {sessionData.script.study_objectives.join(' · ')}
          </p>

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
  return (
    <div className="h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
      <div className="max-w-2xl w-full">
        {branding?.header_image_url && (
          <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
        )}
        {/* Progress */}
        <div className="flex justify-between text-sm text-gray-400 mb-2">
          <span>Question {progress.current} of {progress.total}</span>
          <span>{Math.round((progress.current / Math.max(progress.total, 1)) * 100)}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-1.5 mb-8">
          <div
            className="bg-teal-500 h-1.5 rounded-full transition-all"
            style={{ width: `${(progress.current / Math.max(progress.total, 1)) * 100}%`, backgroundColor: branding?.primary_color }}
          />
        </div>

        {/* Current question — with optional interviewer avatar */}
        <div className="bg-white rounded-xl shadow-sm p-8 mb-6">
          {branding?.interviewer_image_url && (
            <div className="flex items-center gap-3 mb-5 pb-5 border-b border-gray-100">
              <img
                src={branding.interviewer_image_url}
                alt={branding.interviewer_name ?? 'Interviewer'}
                className="w-10 h-10 rounded-full object-cover flex-shrink-0"
              />
              <span className="text-sm font-medium text-gray-600">
                {branding.interviewer_name ?? 'Avery Singh'}
              </span>
            </div>
          )}
          <p className="text-gray-800 text-lg leading-relaxed">{currentQuestion}</p>
        </div>

        {/* Status + Done button */}
        <div className="text-center">
          {statusMessage && (
            <p className="text-teal-600 font-medium animate-pulse mb-4">{statusMessage}</p>
          )}
          {isListening && (
            <button
              onClick={submitAnswer}
              style={{ backgroundColor: branding?.primary_color }}
              className="bg-teal-600 hover:bg-teal-700 text-white font-semibold py-3 px-8 rounded-full text-lg transition-colors shadow-md"
              aria-label="Done speaking"
            >
              ✓ Done
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
