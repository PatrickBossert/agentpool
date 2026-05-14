import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import type { InterviewSession, InterviewScript, InterviewBranding, QuestionnaireTemplateSchema, SectionRatings } from '../types'

type Phase = 'loading' | 'ready' | 'interviewing' | 'assessing' | 'complete' | 'error'

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
  const [sectionRatings, setSectionRatings] = useState<SectionRatings[]>([])
  const [currentAssessSection, setCurrentAssessSection] = useState(0)
  const [pendingRatings, setPendingRatings] = useState<Record<string, number>>({})
  const recognitionRef = useRef<InstanceType<typeof window.webkitSpeechRecognition> | null>(null)
  const qaRef = useRef<{ question: string; answer: string }[]>([])
  const sectionRatingsRef = useRef<SectionRatings[]>([])

  useEffect(() => {
    fetchSession()
  }, [sessionToken])

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
      setPhase('ready')
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
        (window as Window & { SpeechRecognition?: typeof webkitSpeechRecognition }).SpeechRecognition ||
        window.webkitSpeechRecognition
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

      setStatusMessage('Listening…')
      setIsListening(true)

      let silenceTimer: ReturnType<typeof setTimeout> | null = null

      function resetSilenceTimer() {
        if (silenceTimer) clearTimeout(silenceTimer)
        silenceTimer = setTimeout(() => {
          try { recognition.stop() } catch { /* already stopped */ }
        }, 3000)
      }

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        resetSilenceTimer()
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            parts.push(event.results[i][0].transcript)
          }
        }
      }

      recognition.onend = () => {
        if (silenceTimer) clearTimeout(silenceTimer)
        recognitionRef.current = null
        setIsListening(false)
        setStatusMessage('')
        resolve(parts.join(' ').trim())
      }

      recognition.onerror = () => {
        if (silenceTimer) clearTimeout(silenceTimer)
        recognitionRef.current = null
        setIsListening(false)
        setStatusMessage('')
        resolve(parts.join(' ').trim())
      }

      recognition.start()
    })
  }

  function submitAnswer() {
    try { recognitionRef.current?.stop() } catch { /* already stopped */ }
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

  async function runInterview() {
    if (!sessionData) return
    const { session, script } = sessionData
    const voiceId = session.voice_config.elevenlabs_voice_id
    const lang = `${session.voice_config.language}-${session.voice_config.country_code}`

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
      const voiceId = session.voice_config.elevenlabs_voice_id
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
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        {branding?.header_image_url && (
          <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
        )}
        <p className="text-gray-500 text-lg">Loading your interview…</p>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
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
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
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
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
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
                  <span>Optimized</span>
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

  if (phase === 'ready' && sessionData) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="text-center max-w-lg">
          {branding?.header_image_url && (
            <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
          )}
          <h1 className="text-2xl font-bold text-gray-800 mb-2" style={{ color: branding?.text_color }}>
            {sessionData.script.node_label} Interview
          </h1>
          <p className="text-gray-500 mb-8 text-sm">
            {sessionData.script.study_objectives.join(' · ')}
          </p>
          <button
            onClick={runInterview}
            className="bg-teal-600 hover:bg-teal-700 text-white font-semibold py-3 px-8 rounded-lg text-lg transition-colors"
            style={{ backgroundColor: branding?.primary_color }}
          >
            Start Interview
          </button>
          <p className="text-xs text-gray-400 mt-4">
            Ensure your microphone is enabled before starting.
          </p>
        </div>
      </div>
    )
  }

  // interviewing
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
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

        {/* Current question */}
        <div className="bg-white rounded-xl shadow-sm p-8 mb-6">
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
