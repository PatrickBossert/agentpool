import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import type { InterviewSession, InterviewScript } from '../types'

type Phase = 'loading' | 'ready' | 'interviewing' | 'complete' | 'error'

const BASE = '/api'

export default function VoiceInterview() {
  const { sessionToken } = useParams<{ sessionToken: string }>()
  const [phase, setPhase] = useState<Phase>('loading')
  const [sessionData, setSessionData] = useState<{ session: InterviewSession; script: InterviewScript } | null>(null)
  const [currentQuestion, setCurrentQuestion] = useState<string>('')
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const [statusMessage, setStatusMessage] = useState<string>('')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const qaRef = useRef<{ question: string; answer: string }[]>([])

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

  function listenForAnswer(): Promise<string> {
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
      recognition.interimResults = false
      recognition.lang = 'en-GB'

      const parts: string[] = []

      setStatusMessage('Listening… (speak your answer)')

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            parts.push(event.results[i][0].transcript)
          }
        }
      }

      recognition.onend = () => {
        setStatusMessage('')
        resolve(parts.join(' ').trim())
      }

      recognition.onerror = () => {
        setStatusMessage('')
        resolve(parts.join(' ').trim())
      }

      recognition.start()

      // Auto-stop after 30 seconds of max silence
      setTimeout(() => {
        try { recognition.stop() } catch { /* already stopped */ }
      }, 30000)
    })
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

  async function runInterview() {
    if (!sessionData) return
    const { session, script } = sessionData
    const voiceId = session.voice_config.elevenlabs_voice_id

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
        let answer = await listenForAnswer()

        const needsElaboration =
          answer.split(' ').length < 20 ||
          question.evasion_signals.some(sig => answer.toLowerCase().includes(sig.toLowerCase()))

        let followUpCount = 0

        if (needsElaboration) {
          // Press for elaboration
          const pressText = await getElaborationPress(question.text, answer, question.probing_instructions)
          setCurrentQuestion(pressText)
          await speakText(pressText, voiceId)
          const followUpAnswer = await listenForAnswer()
          qaRef.current.push({ question: pressText, answer: followUpAnswer })
          answer = `${answer} ${followUpAnswer}`.trim()
          followUpCount++
        }

        // Pre-scripted follow-up branches
        while (followUpCount < question.follow_up_count && question.follow_up_branches[followUpCount]) {
          const branch = question.follow_up_branches[followUpCount]
          setCurrentQuestion(branch)
          await speakText(branch, voiceId)
          const branchAnswer = await listenForAnswer()
          qaRef.current.push({ question: branch, answer: branchAnswer })
          followUpCount++
        }

        qaRef.current.push({ question: question.text, answer })
      }
    }

    // Closing
    setCurrentQuestion(script.closing_message)
    await speakText(script.closing_message, voiceId)

    // Submit
    setStatusMessage('Saving your responses…')
    await fetch(`${BASE}/interviews/${sessionToken}/complete`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qa_pairs: qaRef.current }),
    })

    setPhase('complete')
    setStatusMessage('')
    setCurrentQuestion('')
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  if (phase === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <p className="text-gray-500 text-lg">Loading your interview…</p>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="text-center">
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
          <div className="text-5xl mb-4">✓</div>
          <h1 className="text-2xl font-bold text-gray-800 mb-2">Thank you!</h1>
          <p className="text-gray-500">Your responses have been recorded. You may now close this window.</p>
        </div>
      </div>
    )
  }

  if (phase === 'ready' && sessionData) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="text-center max-w-lg">
          <h1 className="text-2xl font-bold text-gray-800 mb-2">
            {sessionData.script.node_label} Interview
          </h1>
          <p className="text-gray-500 mb-8 text-sm">
            {sessionData.script.study_objectives.join(' · ')}
          </p>
          <button
            onClick={runInterview}
            className="bg-teal-600 hover:bg-teal-700 text-white font-semibold py-3 px-8 rounded-lg text-lg transition-colors"
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
        {/* Progress */}
        <div className="flex justify-between text-sm text-gray-400 mb-2">
          <span>Question {progress.current} of {progress.total}</span>
          <span>{Math.round((progress.current / Math.max(progress.total, 1)) * 100)}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-1.5 mb-8">
          <div
            className="bg-teal-500 h-1.5 rounded-full transition-all"
            style={{ width: `${(progress.current / Math.max(progress.total, 1)) * 100}%` }}
          />
        </div>

        {/* Current question */}
        <div className="bg-white rounded-xl shadow-sm p-8 mb-6">
          <p className="text-gray-800 text-lg leading-relaxed">{currentQuestion}</p>
        </div>

        {/* Status */}
        {statusMessage && (
          <div className="text-center">
            <p className="text-teal-600 font-medium animate-pulse">{statusMessage}</p>
          </div>
        )}
      </div>
    </div>
  )
}
