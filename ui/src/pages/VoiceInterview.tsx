import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { AlertTriangle, Check, Copy, Pause, Play, ShieldCheck, Undo2 } from 'lucide-react'
import type {
  InterviewSession,
  InterviewScript,
  InterviewBranding,
  MaturityRating,
  SectionMaturityRating,
  SpeechPolicy,
} from '../types'
import {
  browserCanStream,
  browserStreamingObstacle,
  createAudioContext,
  fetchDeepgramGrant,
  openDeepgramSocket,
  startPcmCapture,
  type Recogniser,
  type RecogniserHooks,
} from '../api/deepgram'

// webkit speech recognition types (Chrome/Safari vendor prefix)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const webkitSpeechRecognition: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const SpeechRecognitionEvent: any

/**
 * The interviewer's portrait, as an address this browser can actually fetch.
 *
 * **The `/dashboard` base trap, on the one page it reaches a participant.** Vite serves
 * `ui/public` under the app's base, so the built-in portrait `AGENT_IDENTITY` declares -
 * `/agents/avery-singh.jpg` - is not an address the browser resolves: it 404s, the `<img>`
 * renders as an empty circle, and nothing anywhere says so. That is what the first live
 * interview met on 17 September, and it is the fourth piece of work this trap has caught.
 *
 * The rule the fix follows is the one the dashboard already follows a level over: **the server
 * says which kind of address it handed over**, and the base is this page's knowledge about
 * itself. Nothing here sniffs the shape of the URL - a page that tested for an `/api/` prefix
 * would be restating the server's rule in TypeScript and would break the first time a portrait
 * was served from somewhere else.
 *
 * Exported so it can be driven directly: the property is about the *address*, and a test that
 * only rendered the page would be asserting a string rather than something fetchable.
 */
export function interviewerPortraitSrc(
  imageUrl: string | undefined,
  source: 'served' | 'bundled' | '' | undefined,
): string {
  if (!imageUrl) return ''
  // An absent `source` is a response from before the server named it: rendered verbatim, which
  // is exactly what this page did before, rather than guessed at.
  if (source !== 'bundled') return imageUrl
  // `BASE_URL` ends in a slash and `imageUrl` starts with one; joining them unchanged yields
  // `/dashboard//agents/...`, which resolves but is the same double slash that put
  // `https://host//dashboard/login` in the welcome email.
  return `${import.meta.env.BASE_URL.replace(/\/+$/, '')}${imageUrl}`
}

/**
 * Shorter than this, in words, and an answer is treated as asking to be drawn out.
 *
 * **Chosen against the 17 September interview rather than guessed.** Of its 91 answers, the
 * eleven under nine words are the ones a reader of the transcript would call unelaborated -
 * "No", "It should do", "It's still being established", "Not that I'm aware of", "No all that
 * information is taken on trust" - while nine words up is already substantive: "I would say the
 * controls are not very strong", "I think you have characterised that pretty well actually".
 *
 * So nine presses on **eleven of the ninety-one, and on none of the thirty-one primary
 * answers** - the shortest primary answer in that interview was nine words. That is the balance
 * to keep: a threshold at twelve would have pressed sixteen, including several that had said
 * what they had to say.
 *
 * **A short answer to a yes/no question is not exempt, deliberately.** It is the clearest place
 * an interviewer digs: asked whether there is a threshold and told "No", the useful next
 * question is what it would take to have one. `probing_instructions` reaches
 * `getElaborationPress`, so what gets asked is the script's own line of enquiry rather than a
 * blunt "tell me more".
 */
export const BRIEF_ANSWER_WORDS = 9

/**
 * Whether this answer asks to be pressed - because it is brief, or because it evades.
 *
 * **Two triggers, and brevity is the one that was missing.** The evasion signals are phrases
 * Maya writes at design time, matched as substrings; on the live corpus there are 597 of them
 * across 199 questions and **not one fired in a real interview** - they are what a model
 * imagines somebody will say ("we are on track", "the team manages it") rather than what
 * somebody does. So the whole elaboration loop had never run. They are kept rather than
 * replaced: a signal that does match is a strong one, and the two triggers are independent.
 *
 * An empty answer is **not** pressed. It means the recogniser heard nothing, and the reprompt
 * path already exists for that; asking somebody to expand on a silence is the wrong response to
 * a microphone that failed.
 */
export function needsElaboration(answer: string, evasionSignals: string[] | undefined): boolean {
  const trimmed = answer.trim()
  if (!trimmed) return false
  if (trimmed.split(/\s+/).length < BRIEF_ANSWER_WORDS) return true
  const lower = trimmed.toLowerCase()
  return (evasionSignals ?? []).some(
    sig => sig.trim() !== '' && lower.includes(sig.toLowerCase()),
  )
}

/**
 * Everything the interviewer will say from this script, in the order it will be said.
 *
 * **Only what is scripted.** An elaboration press, a re-prompt and "Of course, go on" are
 * composed while the interview is running and cannot be on this list - which is the whole
 * reason `primeNextUtterance` advances on a *match* rather than on every utterance: a press
 * that moved the cursor would have the interview prefetch the wrong question for ever after.
 *
 * Mirrors `conductInterview`'s own walk, including what that loop deliberately does not speak:
 * the framing block's positioning line alone rather than its bullets and lenses, and of the
 * synthesis check only the peer referral - the rest was withdrawn on 4 September and stays
 * withdrawn. **If either changes, this changes with it**, and the cost of forgetting is a
 * prefetch that misses rather than a wrong interview: the cursor stops matching, the cache
 * stops helping, and every question goes back to being synthesised while somebody waits.
 *
 * A branch is listed only while its `follow_up_count` allows it, because that is the condition
 * the loop asks. It cannot know whether a press will consume one of those slots, so a script
 * whose question draws a press has one listed branch it never reaches - which costs one
 * speculative synthesis and no correctness, since the cursor matches on the words.
 */
export function scriptedSpeech(script: InterviewScript): string[] {
  const plan: string[] = [script.welcome_message]
  if (script.framing_block) plan.push(script.framing_block.positioning)
  for (const section of script.sections) {
    for (const question of section.questions) {
      plan.push(question.text)
      const branches = question.follow_up_branches ?? []
      for (let i = 0; i < question.follow_up_count && branches[i]; i++) plan.push(branches[i])
    }
    if (section.maturity_rating) plan.push(section.maturity_rating.prompt)
  }
  if (script.synthesis_check) plan.push(script.synthesis_check.peer_referral)
  plan.push(script.closing_message)
  return plan.filter(Boolean)
}

/**
 * How long this script says it should take, in minutes - or 0 when it does not say.
 *
 * **Summed from the sections rather than declared once**, because that is where the number
 * lives: `target_minutes` is per section, is on every section of all twelve scripts in
 * `interview_scripts_v9`, and totals between 34 and 54 minutes. A script that omits it
 * anywhere answers 0, and the participant is shown elapsed time alone rather than elapsed time
 * against a target invented here - which is the one thing worse than no target.
 */
export function scriptTimeboxMinutes(sections: { target_minutes?: number }[]): number {
  let total = 0
  for (const section of sections) {
    if (typeof section.target_minutes !== 'number' || !Number.isFinite(section.target_minutes)) {
      return 0
    }
    total += section.target_minutes
  }
  return total
}

/** `m:ss`, with the minutes unbounded - "72:15" rather than "1:12:15". */
function clockFace(totalSeconds: number): string {
  const whole = Math.max(0, Math.floor(totalSeconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

/**
 * What the top bar says about how long this has been going on.
 *
 * **The clock is passed in, never read here.** This project has already lost three tests to a
 * `new Date()` default - `milestoneVariance.test.ts`, which detonated on a particular morning
 * in August - so both ends of the interval are arguments and this function is pure.
 *
 * A clock that goes backwards - a device correcting itself over NTP mid-interview - reads as
 * zero rather than as a negative time. The minutes are unbounded on purpose: "72:15 of 40:00"
 * says what a participant wants to know at a glance, where "1:12:15" has to be compared.
 */
export function elapsedLabel(startedAt: number, now: number, timeboxMinutes: number): string {
  const elapsed = clockFace((now - startedAt) / 1000)
  if (timeboxMinutes <= 0) return elapsed
  return `${elapsed} of ${clockFace(timeboxMinutes * 60)}`
}

/**
 * Elapsed time, in the middle of the top bar.
 *
 * Finding 5 of the first live interview: *"the interview felt very long, but it was probably
 * within the asked-for timebox - I wanted a way of checking."* So it is shown against the
 * timebox wherever the script declares one, which is every live script today.
 *
 * `now` is a **prop**, defaulting to the real clock, so a test drives the time rather than
 * waiting for it. It is not a live region: a timer that announced itself every second would
 * talk over the interviewer.
 */
function ElapsedTime({
  startedAt, timeboxMinutes, now = Date.now,
}: {
  startedAt: number
  timeboxMinutes: number
  now?: () => number
}) {
  const [tick, setTick] = useState(() => now())
  useEffect(() => {
    const timer = setInterval(() => setTick(now()), 1000)
    return () => clearInterval(timer)
  }, [now])

  const over = timeboxMinutes > 0 && tick - startedAt > timeboxMinutes * 60_000
  return (
    <span
      data-testid="elapsed-time"
      aria-label="Time elapsed"
      className={`tabular-nums ${over ? 'text-amber-600' : ''}`}
    >
      {elapsedLabel(startedAt, tick, timeboxMinutes)}
    </span>
  )
}

/** Initials for an interviewer with no headshot - a state agents/identity.py declares legitimate. */
function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]!.toUpperCase())
    .join('')
}

/**
 * The interviewer's face, or their initials - on the two screens a participant meets them.
 *
 * One component rather than the two near-identical blocks it replaces, for the reason
 * `AgentAvatar` gives on the dashboard: the fallback belongs to whatever draws the face, so
 * there is one answer for "no portrait" rather than one per screen. It is *not* `AgentAvatar`,
 * which is dashboard-styled and has no `onError` - and `onError` is the half that matters here.
 *
 * **A truthy address that 404s is the state that reached a participant**, and neither this
 * page's old fallback nor `AgentAvatar`'s would have caught it: both test whether there is a
 * URL, and there was one. So a portrait that fails to load falls back to the initials too - a
 * participant meets a person's initials or a person's face, never an empty circle.
 */
function InterviewerPortrait({
  src, name, className, textClassName,
}: {
  src: string
  name: string
  /** Size, ring and shadow. The caller owns these; the two screens draw different sizes. */
  className: string
  /** Type size for the initials, which differ between the two screens as the circles do. */
  textClassName: string
}) {
  const [broken, setBroken] = useState(false)
  // A new address is a new chance to load: without this, one failure would blank the face for
  // the rest of the interview even after a project uploaded a portrait mid-session.
  useEffect(() => { setBroken(false) }, [src])

  if (!src || broken) {
    return (
      <div
        data-testid="interviewer-initials"
        className={`${className} flex items-center justify-center font-semibold text-white bg-gradient-to-br from-slate-600 to-slate-800 ${textClassName}`}
        aria-hidden="true"
      >
        {initialsOf(name)}
      </div>
    )
  }
  return (
    <img
      data-testid="interviewer-portrait"
      src={src}
      alt={name}
      onError={() => setBroken(true)}
      className={`${className} object-cover`}
    />
  )
}

type Phase =
  | 'loading' | 'mic_setup' | 'ready' | 'interviewing' | 'rating' | 'complete' | 'error'
  // The interview stopped because it could not be transcribed and this engagement forbids the
  // browser's own recogniser. Its own phase rather than `error`, which says "Unable to load
  // interview" - a participant forty minutes in has loaded it perfectly well.
  | 'speech_halted'
type MicStatus = 'no_device' | 'permission_needed' | 'permission_denied' | 'testing' | 'ready'
/** Whether the probe run before the interview begins has been satisfied. */
type SpeechProbe = 'unchecked' | 'checking' | 'ready' | 'unavailable'

const BASE = '/api'

/**
 * Thrown to unwind the interview loop when speech has stopped and may not fall back.
 *
 * The loop is an await over sections and questions, so there is no flag a nested question could
 * set that the enclosing section would see in time - it would speak the next question first. A
 * throw is what actually stops it, and `runInterview` swallows this one because the halt screen
 * is already up by the time it arrives.
 */
class SpeechHalted extends Error {}

/**
 * Which of the closed reasons the server is told, for each way starting Deepgram can fail.
 *
 * `null` means "say nothing": the token door has already recorded and alerted with the HTTP
 * status that distinguishes a refused key from an exhausted balance from a rate limit, and a
 * vague sentence written over a specific one is worse than no second report.
 *
 * The rest are genuinely different problems and must not share a sentence. `capture` is this
 * browser's audio engine refusing to run - on iOS, a context interrupted by a call or the screen
 * locking - and an operator told "the socket would not stay open" checks the key, the balance
 * and the network, none of which is the fault.
 */
function haltReasonForFailureKind(
  kind: 'grant' | 'socket' | 'browser' | 'capture' | 'microphone' | null,
): string | null {
  if (kind === 'grant') return null
  if (kind === 'browser') return 'no_audio_worklet'
  if (kind === 'capture') return 'audio_capture_failed'
  return 'socket_failed'
}

// What a participant is told, in each of the three ways this can end an interview. Plain words
// about what happened, what it means for them, and what to do - never a status code, and never
// the diagnosis the operator gets, which names this deployment's provider and its billing.
const HALT_NO_SERVICE =
  'We are sorry - the transcription service this interview needs is not available at the moment, ' +
  'so we cannot start. Nothing you say could be recorded, and this interview is not permitted to ' +
  'use your browser’s own transcription instead. Please try your link again later, or ' +
  'contact the person who invited you. They have been told.'
// **This no longer names a device, because sp67 stopped there being one to name.** It used to
// send the participant away from Safari and therefore off every iPhone and iPad, which was
// honest while the audio went through `MediaRecorder` and its container. Raw PCM has no
// container, and Safari has had `AudioWorklet` since 14.1 - so what is left is an out-of-date
// browser of any make, and the remedy is to update it rather than to find another device.
const HALT_BROWSER =
  'We are sorry - this interview cannot be conducted in this browser, because it is too old to ' +
  'record audio in the way our transcription service needs, and this interview is not permitted ' +
  'to use your browser’s own transcription instead. Please update your browser, or reopen ' +
  'your interview link in an up-to-date Chrome, Edge, Safari or Firefox. The person who invited ' +
  'you has been told.'
// **Every clause here is something that is now true.** The first version said "Everything you
// answered up to this point has been saved, and nothing has been lost" - and a halted interview
// wrote a `checkpoint_json` that nothing in the product read, left `interview_answers` empty and
// left the session `active`, so the answers were about to be discarded and a participant
// returning to the link would be asked question one again. A participant reads this forty
// minutes in, at the moment it most needs to be true.
//
// The answers are genuinely saved now - `POST /{token}/speech-failure` hands them to the same
// machinery `/complete` uses. **Resumption is still not built**, so this says so plainly rather
// than inviting somebody to reopen a link that will start them over. "Please try your link again
// later" was the clause that did exactly that.
const HALT_MID_INTERVIEW =
  'We are sorry - the transcription service stopped responding, so we have had to end the ' +
  'interview here. The answers you had already given have been saved, so that part of your time ' +
  'is not lost. Reopening this link will not pick up where you left off, so please do not try - ' +
  'the person who invited you has been told, and will arrange anything further with you.'

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
  // **Defaults to `required`, and that is the whole of the fail-closed behaviour on this side.**
  // Until the server has said otherwise - a slow load, a malformed payload, an older API - the
  // browser's own recogniser is refused. The opposite default would make every one of those
  // silently stream a participant's voice to Google.
  const [speechPolicy, setSpeechPolicy] = useState<SpeechPolicy>('required')
  const [speechProbe, setSpeechProbe] = useState<SpeechProbe>('unchecked')
  const [haltNotice, setHaltNotice] = useState('')
  // The listen loop owns closures that outlive a render, so the policy it consults has to be a
  // ref. The state above is what the screens read.
  const speechPolicyRef = useRef<SpeechPolicy>('required')
  const haltedRef = useRef(false)
  // Why the last `startDeepgram` gave up, so a halt can tell a failure the server has already
  // diagnosed from one only this end saw. `grant` means the token door refused, and it alerted
  // with the status code that distinguishes a revoked key from an exhausted balance - reporting
  // again from here wrote "the socket would not open" over it and mailed the operator twice.
  const deepgramFailureKindRef =
    useRef<'grant' | 'socket' | 'browser' | 'capture' | 'microphone' | null>(null)
  // The words already spoken for the current question that no pair holds yet - carried across a
  // "Restart answer" or a "Finish my last answer" by `listenWithRestart`. A ref because the halt
  // lives one closure in, inside `listenForAnswer`, and cannot see that local.
  const carriedTextRef = useRef('')
  const recognitionRef = useRef<Recogniser | null>(null)
  // One microphone stream for the whole interview, and the counters that decide whether
  // Deepgram is still worth asking for. `deepgramOffRef` is one-way once set: every later
  // answer goes straight to the browser's recogniser rather than paying a failed round trip in
  // front of the participant.
  //
  // **Two ways to reach it, counted separately, and a single mid-answer drop is no longer one
  // of them.** `deepgramFailuresRef` counts consecutive failures to *open* - two in a row is a
  // deployment without Deepgram. `deepgramDropsRef` counts sockets that opened and then went
  // away, which cannot share that counter: a successful open resets the first one, so a drop
  // recorded there could never accumulate past one. Setting the switch on the first drop meant
  // one transient blip condemned the rest of the interview to a recogniser that has never
  // heard of the client, which is the whole thing this branch exists to fix.
  const interviewStreamRef = useRef<MediaStream | null>(null)
  // The audio graph's context, held beside the stream and released with it - see
  // `interviewAudioContext` for why it is one per interview rather than one per answer.
  const audioContextRef = useRef<AudioContext | null>(null)
  const deepgramFailuresRef = useRef(0)
  const deepgramDropsRef = useRef(0)
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
  // When the participant tapped Start, which is what the elapsed clock counts from. `null`
  // until then, so the top bar has nothing to show rather than a zero that has not started.
  const [startedAt, setStartedAt] = useState<number | null>(null)
  // Everything the interviewer will say, in order, and how far down it playback has got. The
  // pair is what lets one utterance be synthesised while the previous one is being heard.
  const speechPlanRef = useRef<string[]>([])
  const planCursorRef = useRef(0)
  // Audio asked for but not yet spoken, keyed on the words. At most two entries live: the one
  // being said and the one after it.
  const speechAheadRef = useRef<Map<string, Promise<Blob | null>>>(new Map())
  // The whole pair, not `{question, answer}`. The corrected answers are re-submitted to
  // `/complete` when the participant finishes, and that door requires `question_id` on every
  // pair - narrowing the type here is how an edit would have been sent without its address.
  const [editableTranscript, setEditableTranscript] = useState<CapturedPair[]>([])
  const [savingCorrections, setSavingCorrections] = useState(false)
  const [finished, setFinished] = useState(false)
  // Three outcomes, not two. "Not copied yet" and "this browser would not copy" are different
  // things to a participant, and a boolean can only say one of them.
  const [copyOutcome, setCopyOutcome] = useState<'idle' | 'copied' | 'unavailable'>('idle')
  // Set when the corrections could not be saved. Finding I4: this screen used to say "Your
  // responses have been recorded" whatever `/complete` answered, and then unmounted the
  // transcript - so a participant who lost connectivity was told their corrections had landed
  // and left with no way to try again.
  const [finishError, setFinishError] = useState('')
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
    if (phase === 'complete' || phase === 'error' || phase === 'speech_halted') {
      releaseInterviewStream()
    }
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

  // The probe, at device setup and nowhere else.
  //
  // **Before the interview begins, not during it.** A participant on an engagement that forbids
  // the browser's recogniser has to be told they cannot proceed before they start, not after
  // thirty answers - which is what a mid-interview discovery would mean, and the whole reason
  // this runs here rather than at the first question.
  useEffect(() => {
    if (phase === 'ready' && speechPolicy === 'required' && speechProbe === 'unchecked') {
      void probeSpeech()
    }
  }, [phase, speechPolicy, speechProbe])

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
      // **The server's decision, taken as given.** `browser_permitted` is the only value that
      // opens the fallback; anything else - `required`, a missing key, a value this build has
      // never heard of - closes it. Written as an allow-list rather than as `=== 'required'`
      // for the reason CLAUDE.md gives about the skills-library exemptions: a third value must
      // prove itself rather than inherit the permissive branch by not being named.
      const policy: SpeechPolicy =
        data.speech_policy === 'browser_permitted' ? 'browser_permitted' : 'required'
      setSpeechPolicy(policy)
      speechPolicyRef.current = policy
      // Inline maturity ratings are embedded in section.maturity_rating — no separate questionnaire

      const micOk = await checkMicDevices()
      setPhase(micOk ? 'ready' : 'mic_setup')
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unknown error')
      setPhase('error')
    }
  }

  /**
   * Tell the server an interview could not be transcribed. Never throws.
   *
   * A closed vocabulary rather than a sentence: the door is unauthenticated and what it produces
   * lands in an administrator's alert, so the wording is composed on the server and the browser
   * only says which case it is.
   *
   * **A side effect must not veto the thing it is a side effect of.** The participant has already
   * been refused by the time this runs, and a failed report must not turn a handled refusal into
   * a thrown error on the one screen that is trying to explain itself.
   */
  async function reportSpeechFailure(
    reason: string | null,
    answers: CapturedPair[] = [],
    ratings: SectionMaturityRating[] = [],
  ): Promise<void> {
    try {
      await fetch(`${BASE}/interviews/${sessionToken}/speech-failure`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // The answers ride with the report rather than going to a door of their own: one
        // request, and the server decides the order - preserve, then alert - so a slow or
        // failing alert can never cost a participant their answers.
        body: JSON.stringify({ reason, qa_pairs: answers, ratings: ratings.length ? ratings : undefined }),
      })
    } catch {
      // The server's own log is the other leg of this alert. Nothing here is worth failing on.
    }
  }

  /**
   * Everything said so far, kept where a reconnecting session would find it. Never throws.
   *
   * **`partial_answer` is not padding.** `qaRef` gains a pair only when an answer *completes*, so
   * a halt part-way through one would otherwise discard exactly the words the participant was
   * speaking when the service went - which on the first question of an interview is all of them.
   * It carries no question id because it has none: the pair is built by the interview loop after
   * `listenForAnswer` returns, and inventing an id here would put an answer under an address
   * nothing else agrees with. The words are what must not be lost.
   */
  async function preserveProgress(partialAnswer: string): Promise<void> {
    try {
      await fetch(`${BASE}/interviews/${sessionToken}/checkpoint`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          checkpoint: {
            qa_pairs: qaRef.current,
            ratings: sectionRatingsRef.current,
            partial_answer: partialAnswer,
          },
        }),
      })
    } catch {
      // Best effort. The halt screen is shown either way - telling a participant the interview
      // has stopped matters more than the checkpoint, and saying nothing is the failure.
    }
  }

  /**
   * Can this interview be conducted at all? Asked once, at device setup.
   *
   * **Two questions, not one**, and either failing refuses the interview:
   *
   *  1. **Can this browser capture audio for us at all?** Raw PCM comes out of an `AudioWorklet`,
   *     so this arm asks whether the browser has one. It fails for reasons that have nothing to
   *     do with Deepgram, and on this kind of engagement it must still mean "cannot proceed" -
   *     the alternative is the participant's voice going to Google or Apple.
   *
   *     **It used to ask a much narrower question and refuse a great many more people.** While
   *     the audio went through `MediaRecorder`, the browser negotiated a container and Safari
   *     negotiated MP4/AAC against a socket opened for webm/opus, so this arm declined every
   *     iPhone and iPad. Raw PCM negotiates nothing, and Safari has had `AudioWorklet` since
   *     14.1 on macOS and iOS 14.5, so what is left is an out-of-date browser rather than a
   *     device.
   *  2. **Is Deepgram reachable and in credit?** Minting a grant is the same call the interview
   *     makes, so a refused key or an exhausted balance fails here. The grant is then discarded -
   *     it lives thirty seconds and could not be held for the first question anyway - and that
   *     small waste is the price of asking the question honestly rather than assuming.
   *
   * The first is asked first deliberately: it needs no network, and a browser that could never
   * have worked should not be reported to an administrator as a Deepgram outage.
   *
   * **Nothing here opens a socket to any speech service.** The grant is fetched from this
   * deployment's own API; a refusal ends the probe with no `WebSocket` constructed anywhere and
   * no `SpeechRecognition` started, which is the entire point of probing rather than trying.
   */
  async function probeSpeech(): Promise<void> {
    setSpeechProbe('checking')
    const obstacle = browserStreamingObstacle()
    if (obstacle) {
      setHaltNotice(obstacle === 'no_audio_worklet' ? HALT_BROWSER : HALT_NO_SERVICE)
      setSpeechProbe('unavailable')
      await reportSpeechFailure(obstacle)
      return
    }
    const grant = await fetchDeepgramGrant(BASE, sessionToken ?? '')
    if (!grant) {
      // The token door has already recorded and alerted for this half: it is the only place that
      // holds the status code telling a refused key from an exhausted balance from a rate limit,
      // and an administrator sent to check all three has been told nothing useful.
      setHaltNotice(HALT_NO_SERVICE)
      setSpeechProbe('unavailable')
      return
    }
    setSpeechProbe('ready')
  }

  /**
   * Stop the interview, keep what has been answered, and tell everyone who needs to know.
   *
   * Reached when transcription fails *during* an interview on an engagement that forbids the
   * fallback - credit expiring at answer thirty, a socket that will not reopen. Falling back to
   * Google is exactly what the probe exists to prevent, so it cannot be the mid-interview answer
   * either.
   *
   * Preserve first, then report, then show the screen. The order is deliberate: an alert that
   * arrived before the answers were saved would be an alert about an interview whose answers
   * might not have been.
   */
  async function haltForSpeechFailure(reason: string | null, partialAnswer = ''): Promise<void> {
    if (haltedRef.current) return
    haltedRef.current = true
    setHaltNotice(HALT_MID_INTERVIEW)
    // Two different things are being kept, and only one of them can become a row. The completed
    // answers go to the server as `qa_pairs` and are written to `interview_answers`, which is
    // what the crews read. The words spoken into the failing socket have no question id - the
    // interview loop builds the pair after the listen resolves, and it never will - so the
    // checkpoint is the only thing that can hold them.
    await preserveProgress(partialAnswer)
    await reportSpeechFailure(reason, qaRef.current, sectionRatingsRef.current)
    setPhase('speech_halted')
  }

  /**
   * Ask the speak door for one utterance, at most once at a time.
   *
   * Keyed on the text, so the prefetch below and the `speakText` that later wants the same
   * words share **one** request rather than racing: whichever arrives first, the other awaits
   * the same promise.
   *
   * **A failure is never cached.** `null` means this utterance could not be had *this time* - a
   * refused request, a dropped connection - and leaving that in the map would silently mute
   * that question for the rest of the interview, which is a worse outcome than the round trip
   * the cache exists to save. So the entry removes itself and the next asker tries again.
   */
  function requestSpeech(text: string): Promise<Blob | null> {
    const inFlight = speechAheadRef.current.get(text)
    if (inFlight) return inFlight
    const pending = fetch(`${BASE}/interviews/${sessionToken}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
      .then(async res => {
        if (!res.ok) {
          // Non-fatal: skip audio, continue.
          console.warn('speak endpoint error', res.status)
          return null
        }
        return await res.blob()
      })
      .catch(() => null)
      .then(blob => {
        if (!blob) speechAheadRef.current.delete(text)
        return blob
      })
    speechAheadRef.current.set(text, pending)
    return pending
  }

  /**
   * Start synthesising whatever comes next, while this utterance is still being said.
   *
   * **Measured, not guessed.** In the 17 September interview 95 of the 96 speak calls were
   * cache misses - every question synthesised live with the participant waiting - because
   * `prewarm_script_audio` on the server has no production caller and the cache key includes
   * the voice, so sp62's per-project voice invalidated the entries a previous run had left.
   * The idle time is real: an utterance plays for fifteen to twenty seconds and the answer to
   * it takes twenty more, against a synthesis of a few seconds.
   *
   * **One ahead, and only after the current blob is in hand**, so the prefetch never competes
   * with the request somebody is actually waiting on.
   *
   * The cursor advances only when what was just spoken *is* the next planned utterance, which
   * is what keeps a dynamic one - an elaboration press, a re-prompt, "Of course, go on" - from
   * skipping a question. It is a position rather than a search, so two questions with the same
   * words cannot confuse it.
   */
  function primeNextUtterance(justSpoken: string): void {
    const plan = speechPlanRef.current
    if (plan[planCursorRef.current] !== justSpoken) return
    planCursorRef.current += 1
    const next = plan[planCursorRef.current]
    if (next) void requestSpeech(next)
  }

  async function speakText(text: string): Promise<void> {
    setStatusMessage('Speaking…')
    const blob = await requestSpeech(text)
    speechAheadRef.current.delete(text)
    // After the await, so the next utterance is synthesised during this one rather than beside
    // it. Before the playback await, so it has the whole of the utterance to be ready in.
    primeNextUtterance(text)
    if (!blob) {
      setStatusMessage('')
      return
    }
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
      // Read the flag before setting it: an engine interrupted by its own caller reports
      // `aborted`, and a notice on every "Done speaking" would put the amber box in front of
      // every participant on every answer.
      const requested = stopping
      // Whatever the error, do not restart: let onend close the answer out.
      stopping = true
      if (requested) return
      // Silence is the ordinary end of an answer, not a failure. The countdown has already
      // said everything there is to say about it.
      if (event.error === 'no-speech') return
      if (
        event.error === 'not-allowed' ||
        event.error === 'service-not-allowed' ||
        // The device is gone, or another application has taken it. A different remedy from a
        // transcription failure, and told in different words.
        event.error === 'audio-capture'
      ) {
        hooks.onDropped('microphone')
        return
      }
      // **Everything else, including `network`.** This arm did not exist until sp66's final
      // review: `network` is Chrome's *routine* failure, because Web Speech streams the audio
      // to Google, and it fell through here to an `onend` that closed the answer with nothing
      // in it and set no notice at all. On a deployment with no Deepgram key - which is every
      // deployment before sp66 - that is every answer of the interview, recorded empty, in
      // front of a participant watching a countdown.
      hooks.onDropped('connection')
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
    // Chrome caps a page at six concurrent `AudioContext`s, and one that is never closed keeps
    // the audio hardware awake after the interview has finished.
    const context = audioContextRef.current
    audioContextRef.current = null
    if (context) { try { void context.close() } catch { /* already gone */ } }
  }

  /**
   * The `AudioContext` the capture graph runs in, acquired once and kept.
   *
   * The same argument as the microphone stream above, with an iOS-specific third: Safari starts a
   * context suspended and reports a fourth state, `interrupted`, when the participant switches
   * tabs or lets the screen lock. `startPcmCapture` resumes it before every answer, which is
   * cheap on a context that is already running and is the only thing that brings back one that
   * is not - and doing that to one long-lived context is a great deal more reliable than
   * constructing a fresh one inside an answer loop, where there is no user gesture in the call
   * chain at all.
   */
  function interviewAudioContext(): AudioContext | null {
    if (!audioContextRef.current) audioContextRef.current = createAudioContext()
    return audioContextRef.current
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
    if (deepgramOffRef.current || !browserCanStream()) {
      deepgramFailureKindRef.current = 'browser'
      return null
    }
    const grant = await fetchDeepgramGrant(BASE, sessionToken ?? '')
    if (!grant) {
      // **The server has already recorded and alerted for this one, with the diagnosis only it
      // could produce.** `GET /{token}/deepgram-token` holds the HTTP status that tells a refused
      // key from an exhausted balance from a rate limit; all this end knows is "no grant". Saying
      // so here is what let the vague sentence be written over the specific one.
      deepgramFailureKindRef.current = 'grant'
      return null
    }
    const stream = await interviewStream()
    if (!stream) {
      deepgramFailureKindRef.current = 'microphone'
      return null
    }
    const context = interviewAudioContext()
    if (!context) {
      // No Web Audio at all. Reported as a browser failure rather than a socket one: nothing was
      // opened, and an administrator sent to check Deepgram would be looking in the wrong place.
      deepgramFailureKindRef.current = 'browser'
      return null
    }
    // **Two calls, because they fail for different reasons and an operator is sent to different
    // places.** A capture that will not start is this browser's audio engine - on iOS, a context
    // that would not resume - and reporting it as a socket failure tells an administrator to
    // check the Deepgram key, the balance and the network, every one of which is fine.
    const capture = await startPcmCapture(stream, context)
    if (!capture) {
      deepgramFailureKindRef.current = 'capture'
      return null
    }
    deepgramFailureKindRef.current = 'socket'
    const engine = await openDeepgramSocket(capture, grant, hooks)
    if (engine) deepgramFailureKindRef.current = null
    // The socket declining owns the teardown from the moment it was handed the capture, so
    // there is nothing to release here - see `settle` in `openDeepgramSocket`.
    return engine
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
    return new Promise((resolve, reject) => {
      const parts: string[] = []
      let resolved = false
      let engine: Recogniser | null = null
      // **Which engine is listening, because a drop means different things on each.** Deepgram
      // going away has somewhere to go - the browser's recogniser picks up the same answer. The
      // browser's recogniser going away has nowhere: it *is* the fallback. Handing that drop to
      // the handover branch would start a second browser recogniser on an engine that has just
      // failed, so the distinction is structural rather than a nicety.
      let engineKind: 'deepgram' | 'browser' | null = null
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

      /**
       * End the whole interview rather than this answer, and hand nothing to the browser.
       *
       * Rejects rather than resolving: the interview is an await loop, so an answer that simply
       * resolved would be followed by the next question being spoken. `runInterview` catches
       * `SpeechHalted` and does nothing, because `haltForSpeechFailure` has already put the halt
       * screen up.
       */
      function halt(reason: string | null) {
        if (resolved) return
        resolved = true
        recognitionRef.current = null
        clearSilenceTimers()
        setSilenceProgress(0)
        setIsListening(false)
        setStatusMessage('')
        setInterimText('')
        // The words heard so far on *this* answer, which no pair holds yet - the interview loop
        // builds the pair after this promise settles, and it never will now. `carriedTextRef` is
        // the same thing one closure out: anything said before the participant tapped "Restart
        // answer" or "Finish my last answer", which `listenWithRestart` holds and this cannot see.
        const spoken = [carriedTextRef.current, parts.join(' ').trim()].filter(Boolean).join(' ')
        void haltForSpeechFailure(reason, spoken)
        reject(new SpeechHalted(reason ?? 'already reported'))
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
            // The microphone has gone - refused, revoked, unplugged, or taken by another
            // application - and so it has for any other engine. There is nothing to hand over
            // to; onClosed follows and ends the answer. The sentence covers both causes
            // because the engine reports them as one thing to us and the participant has to
            // check both.
            setRecogniserNotice(
              'We have lost access to your microphone. Check that it is connected and that ' +
              'this page is allowed to use it, then use Done to carry on.',
            )
            return
          }
          if (engineKind === 'browser') {
            // The browser's own recogniser has dropped, and it is the last engine there is.
            // Nothing to hand over to, so the honest thing is to say what happened, keep what
            // was heard, and point at the correction step that actually exists - onClosed
            // follows and closes the answer.
            setRecogniserNotice(
              'We stopped hearing you - your browser’s transcription dropped out. Anything ' +
              'already heard has been kept, but the end of that answer may be missing. The ' +
              'interview carries on, and you can correct every answer before you finish.',
            )
            return
          }
          // The socket dropped mid-answer. The participant is still talking, so the worst
          // possible response is to end the answer quietly and let them finish into nothing.
          // Hand the rest of this same answer to the browser's recogniser, keep what was
          // already heard, and say what happened - both halves, not either.
          //
          // **Not on an engagement that forbids the fallback.** The browser's recogniser streams
          // to Google or to Apple, and "the socket dropped" is not a reason to do that - it is
          // the exact circumstance the probe at device setup exists to prevent, arriving later.
          // So the interview stops here instead, keeping what was answered.
          if (speechPolicyRef.current === 'required') {
            halt('socket_failed')
            return
          }
          // **Start it before claiming it.** The notice used to be set first and said "the
          // interview is carrying on using your browser to transcribe. Please continue." -
          // and then `startWebSpeech` answered `null`, which is what it does in Firefox. The
          // participant kept talking into nothing on the strength of that sentence. A claim
          // about a handover is a claim about something that has already happened.
          const handover = startWebSpeech(lang, hooks)
          engineKind = handover ? 'browser' : null
          if (!handover) {
            setRecogniserNotice(
              'The transcription service dropped out, and this browser cannot transcribe on ' +
              'its own - so nothing you say from here is being recorded. Anything already ' +
              'heard has been kept. Please reopen your interview link in Chrome or Edge, or ' +
              'contact the person who invited you.',
            )
            finish()
            return
          }
          engine = handover
          // Counted, not latched. One blip must not cost the rest of the interview the only
          // recogniser that has been told this engagement's own words.
          deepgramDropsRef.current += 1
          if (deepgramDropsRef.current >= 2) deepgramOffRef.current = true
          setRecogniserNotice(
            'The transcription service dropped out. What you have said so far has been kept, ' +
            'and the interview is carrying on using your browser to transcribe. Please continue.',
          )
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
          // The probe passed at device setup and Deepgram has gone since - an expiring balance,
          // a key revoked mid-engagement, a network that came and went. The fallback is refused
          // here for the same reason it is refused on a drop: it would send this participant's
          // voice to their browser vendor, which is what this engagement does not permit.
          //
          // **`null` when the token door refused**, because it has already recorded and alerted
          // with the status code that says which problem it was. `probeSpeech` has made exactly
          // this judgement since the branch landed and says why; carrying it here is the whole
          // of the repair. Without it, the balance running out at answer twelve wrote "the
          // socket would not open" over "the balance is exhausted or the card has expired" and
          // mailed the operator twice for one incident.
          if (speechPolicyRef.current === 'required') {
            halt(haltReasonForFailureKind(deepgramFailureKindRef.current))
            return
          }
          deepgramFailuresRef.current += 1
          // Two in a row is a deployment without Deepgram, not a bad moment. Stop asking: a
          // failed round trip before every answer is latency a participant sits through.
          if (deepgramFailuresRef.current >= 2) deepgramOffRef.current = true
          engine = startWebSpeech(lang, hooks)
          engineKind = engine ? 'browser' : null
        } else {
          engineKind = 'deepgram'
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
    //
    // **Mirrored into `carriedTextRef` on every change**, because a halt happens one closure in,
    // inside `listenForAnswer`, which cannot see this local. Without the mirror these words went
    // with the socket - the same class as the in-flight answer, one closure further out, and a
    // participant who had tapped "Finish my last answer" would lose the most of anybody.
    let carried = ''
    carriedTextRef.current = ''
    // eslint-disable-next-line no-constant-condition
    while (true) {
      setInterimText('')
      const heard = await listenForAnswer(lang)

      if (restartAnswerRef.current) {
        restartAnswerRef.current = false
        carried = ''
        carriedTextRef.current = ''
        setStatusMessage('Restarting…')
        await new Promise(r => setTimeout(r, 300))
        setStatusMessage('')
        continue
      }

      if (appendToPreviousRef.current) {
        appendToPreviousRef.current = false
        carried = [carried, heard].filter(Boolean).join(' ').trim()
        carriedTextRef.current = carried
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

      // The answer is about to become a pair, so nothing is carried any more. Cleared here as
      // well as on entry, or a halt on a *later* question would re-send words that already
      // reached the transcript under their own question.
      carriedTextRef.current = ''
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
  async function postCompletion(
    pairs: CapturedPair[],
    ratings: SectionMaturityRating[],
  ): Promise<boolean> {
    try {
      const res = await fetch(`${BASE}/interviews/${sessionToken}/complete`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          qa_pairs: pairs,
          ratings: ratings.length > 0 ? ratings : undefined,
        }),
      })
      // **Answered, not swallowed.** Both arms of this used to `console.warn` and return, and
      // `handleFinishInterview` then set `finished` unconditionally - so a participant who had
      // spent forty-five minutes on the page, lost connectivity, corrected three mangled answers
      // and tapped Finish was told "Your responses have been recorded", and the transcript was
      // unmounted behind that sentence with no way to try again. It is the one button the
      // participant triggers and is told about, which is the exact shape this branch exists to
      // remove.
      if (!res.ok) {
        console.warn('complete endpoint returned', res.status)
        return false
      }
      return true
    } catch (err) {
      console.error('Failed to submit responses', err)
      return false
    }
  }

  async function submitResponses(ratings: SectionMaturityRating[]) {
    setStatusMessage('Saving your responses…')
    // The answer is deliberately not acted on here, and this is not the same omission as I4. The
    // review screen this moves to *is* the retry: it carries every answer, and Finish resubmits
    // the lot to the same door. Refusing to show it would strand a participant who has finished
    // speaking, on the one path where nothing has been claimed to them yet.
    await postCompletion(qaRef.current, ratings)
    setPhase('complete')
    setStatusMessage('')
    setCurrentQuestion('')
  }

  /**
   * Start the interview, and absorb the one way it can stop rather than finish.
   *
   * `SpeechHalted` is thrown out of `listenForAnswer` when transcription has failed on an
   * engagement that forbids the browser's recogniser. By the time it arrives here the halt screen
   * is already up, the answers are checkpointed and the failure is reported, so there is nothing
   * left to do but stop unwinding. Anything else is a real fault and is left to propagate.
   */
  async function runInterview() {
    // **Built here, synchronously, because this runs in the task the Start click created.**
    // iOS starts an `AudioContext` suspended when it is constructed outside a user gesture, and
    // whether `resume()` is then granted on sticky activation alone is exactly the thing nobody
    // has driven on a real device. Constructed lazily at the first answer it certainly *was*
    // outside one - `conductInterview` awaits `PATCH /status` and then the interviewer speaking
    // before anything reaches `startDeepgram`, so the gesture's task had long since yielded.
    // The refusal is clean either way (the capture declines rather than capturing silence), but
    // a clean refusal at question one on every iPhone is this branch's headline claim inverted.
    // Nothing here depends on the context being usable, so a browser without Web Audio is
    // unaffected: the probe has already refused it, and `startDeepgram` re-asks.
    interviewAudioContext()
    try {
      await conductInterview()
    } catch (err) {
      if (err instanceof SpeechHalted) return
      throw err
    }
  }

  async function conductInterview() {
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

    // The clock starts when the interview does, not when the page loaded - a participant who
    // left the device-setup screen open over lunch has not been interviewed for an hour.
    setStartedAt(Date.now())
    speechPlanRef.current = scriptedSpeech(script)
    planCursorRef.current = 0
    speechAheadRef.current.clear()
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
        const answer = await listenWithRestart(lang, { text: question.text })

        let followUpCount = 0
        // Presses are numbered independently of branches, so a press on a branch answer cannot
        // collide with a branch's own id. `F` and `B` are separate series in `capturedPair`.
        let pressCount = 0

        /**
         * Press once on an answer that asks for it, and return what came back.
         *
         * **Asked of branch answers as well as of the primary one**, which is where the
         * reported defect actually lives: in the 17 September interview 60 of the 91 answers
         * were to scripted branches, every answer under nine words was one of them, and this
         * code had never looked at a branch answer at all. Pressing only the primary answer
         * would have reached one of the eleven short ones.
         *
         * A press's *own* answer is never pressed again - the recursion is not there, and it is
         * the bound that keeps a brief reply from becoming an interrogation. An empty press
         * means none was produced in time, so the whole branch is skipped and the interview
         * moves on: a missed follow-up costs depth on one answer, while speaking nothing and
         * then listening costs the interviewee's confidence in the whole conversation.
         */
        const pressFor = async (asked: string, reply: string): Promise<string> => {
          if (!needsElaboration(reply, question.evasion_signals)) return ''
          const pressText = await getElaborationPress(asked, reply, question.probing_instructions)
          if (!pressText) return ''
          setCurrentQuestion(pressText)
          await speakText(pressText)
          const followUpAnswer = await listenWithRestart(lang)
          pressCount++
          qaRef.current.push(capturedPair(
            scriptId, sectionId, questionNo, pressText, followUpAnswer,
            { kind: 'F', index: pressCount },
          ))
          return followUpAnswer
        }

        // **Recorded the moment it is given, and merged into afterwards.** The pair used to be
        // pushed *after* the press, so an interview that halted during one - a grant refused,
        // a socket that would not open - lost the answer it had just been given: it was in no
        // pair, and `halt` can only carry what the *current* listen heard. Pre-existing, and
        // pressing on brevity would have made it common. Pushing first also puts the pairs in
        // the order they happened, which is the order the review screen shows them in.
        const primaryPair = capturedPair(scriptId, sectionId, questionNo, question.text, answer)
        qaRef.current.push(primaryPair)

        const elaboration = await pressFor(question.text, answer)
        if (elaboration) {
          primaryPair.answer = `${primaryPair.answer} ${elaboration}`.trim()
          // A press has always consumed a branch slot: it asked the thing the first scripted
          // branch was there to ask.
          followUpCount++
        }

        // Pre-scripted follow-up branches
        while (followUpCount < question.follow_up_count && question.follow_up_branches[followUpCount]) {
          const branch = question.follow_up_branches[followUpCount]
          const branchIndex = followUpCount + 1
          setCurrentQuestion(branch)
          await speakText(branch)
          const branchAnswer = await listenWithRestart(lang)
          followUpCount++
          // Recorded before its press and merged into afterwards, exactly as the primary
          // answer above is, and for the same reason.
          const branchPair = capturedPair(
            scriptId, sectionId, questionNo, branch, branchAnswer, { kind: 'B', index: branchIndex },
          )
          qaRef.current.push(branchPair)
          const drawnOut = await pressFor(branch, branchAnswer)
          if (drawnOut) branchPair.answer = `${branchPair.answer} ${drawnOut}`.trim()
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
    // This is the one listen the interview loop does not await directly - it is kicked off with
    // `void` and resolves through `ratingResolveRef`. So a halt thrown here has no await to
    // unwind into, and it is caught rather than left as an unhandled rejection. The rating
    // promise is then deliberately never resolved: the loop parks on it, which is correct, since
    // the halt screen has replaced the interview and nothing further may be spoken or recorded.
    let spoken: string
    try {
      spoken = await listenForAnswer(lang)
    } catch (err) {
      if (err instanceof SpeechHalted) return
      throw err
    }
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

  /**
   * The older clipboard route, which is the only one a page has in a non-secure context.
   *
   * `document.execCommand('copy')` is deprecated and still works everywhere, including over
   * plain http where `navigator.clipboard` does not exist at all. It is tried before giving up,
   * because making the claim true is better than withdrawing it: an on-premises deployment
   * served over http is exactly the secure-mode customer, and this button is the only route a
   * participant has to their own transcript since the email route was removed.
   *
   * Answers `false` rather than throwing for every way it can fail, including a browser that
   * does not implement it at all, so the caller has one thing to test.
   */
  function copyByExecCommand(text: string): boolean {
    try {
      const carrier = document.createElement('textarea')
      carrier.value = text
      carrier.setAttribute('readonly', '')
      carrier.style.position = 'fixed'
      carrier.style.top = '0'
      carrier.style.opacity = '0'
      document.body.appendChild(carrier)
      carrier.select()
      const exec = (document as unknown as { execCommand?: (c: string) => boolean }).execCommand
      const ok = typeof exec === 'function' && exec.call(document, 'copy') === true
      document.body.removeChild(carrier)
      return ok
    } catch {
      return false
    }
  }

  /**
   * Copy the transcript, and say what actually happened.
   *
   * This read `await navigator.clipboard?.writeText(...)` inside a `try`, with a comment saying
   * it left the button saying "Copy rather than claiming a copy that did not happen". It did
   * the opposite: `navigator.clipboard` is **undefined in every non-secure context**, the
   * optional chain short-circuits to `undefined`, and `await undefined` does not throw - so the
   * `catch` covered a clipboard that exists and rejects, and nothing at all covered a browser
   * with no clipboard. The button said "Copied" over an empty clipboard, on the one screen
   * whose whole purpose is to stop telling a participant something had worked when it had not.
   */
  async function handleCopyTranscript() {
    const text = transcriptAsText()
    if (typeof navigator.clipboard?.writeText === 'function') {
      try {
        await navigator.clipboard.writeText(text)
        setCopyOutcome('copied')
        return
      } catch {
        // Present and refused - a permission prompt declined, or a document without focus.
        // Fall through: the older route often still works.
      }
    }
    setCopyOutcome(copyByExecCommand(text) ? 'copied' : 'unavailable')
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
    setFinishError('')
    const saved = await postCompletion(editableTranscript, sectionRatingsRef.current)
    setSavingCorrections(false)
    if (!saved) {
      // The transcript stays on screen, every field still editable, and Finish is still there to
      // press again. Telling the truth is necessary and not sufficient: a participant told it
      // failed and left with nothing to press has still lost their corrections.
      setFinishError(
        'We could not save your corrections just now - the connection did not reach us. Your ' +
        'original answers are safe, but the changes you have made on this page are not saved ' +
        'yet. Please check your connection and press Finish again. If it keeps failing, use ' +
        'Copy above to keep your own copy before you close this window.',
      )
      return
    }
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

  // The interview could not be transcribed, and this engagement does not permit the browser's own
  // recogniser. Its own screen rather than `error`, which says "Unable to load interview" - the
  // page loaded perfectly well and the participant may be forty minutes into it. It apologises,
  // says what has been kept, and asks them to come back, because there is nothing they can do
  // about a transcription provider and telling them to try another browser would be a lie on two
  // of the three routes here.
  if (phase === 'speech_halted') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6 overflow-y-auto">
        <div className="max-w-lg w-full text-center">
          {branding?.header_image_url && (
            <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
          )}
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-amber-50 mb-3">
            <AlertTriangle size={24} className="text-amber-600" aria-hidden="true" />
          </div>
          <h1 className="text-2xl font-bold text-gray-800 mb-2">We have had to stop here</h1>
          <p
            role="alert"
            data-testid="speech-halted-notice"
            className="text-gray-600 text-sm leading-relaxed"
          >
            {haltNotice || HALT_MID_INTERVIEW}
          </p>
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
                      {/* **White on dark grey, and deliberately not a branding colour.**
                          Finding 10 of the 17 September interview: the question was
                          `text-gray-600` on `bg-gray-50` and the answer `text-gray-700` on
                          white, so on a screen carrying dozens of pairs there was almost
                          nothing to tell one from the other at a glance. A dark band reads as
                          "asked" against a light field that reads as "said".

                          A project sets `primary_color` and `text_color` and neither is used
                          here, on purpose: this pair is chosen for contrast and checked, and
                          deriving either half from an operator's colour picker would make the
                          legibility of the one screen where a participant corrects their own
                          words depend on a choice made for a logo. The heading and the buttons
                          above still carry the branding, so the page is still theirs. */}
                      <div className="px-4 py-3 bg-slate-700">
                        <p
                          id={`review-question-${i}`}
                          data-testid="review-question"
                          className="text-sm text-white leading-relaxed"
                        >
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
                            setCopyOutcome('idle')
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
                        <Copy size={14} />
                        {copyOutcome === 'copied'
                          ? 'Copied'
                          : copyOutcome === 'unavailable'
                            ? 'Could not copy'
                            : 'Copy'}
                      </button>
                      {/* Withdrawing the false claim is necessary and not sufficient. A
                          participant told "could not copy" and left with 59 separate answer
                          fields has still lost their transcript, so the whole text is offered
                          in one selectable field - a route they can actually take. Read-only:
                          this is the copy, not a second place to correct the answers. */}
                      {copyOutcome === 'unavailable' && (
                        <div className="mt-3" data-testid="copy-by-hand">
                          <p className="text-sm text-gray-700">
                            This browser would not let the page copy for you. Your transcript is
                            below - select it all and copy it yourself.
                          </p>
                          <textarea
                            readOnly
                            aria-label="Your transcript"
                            value={transcriptAsText()}
                            rows={10}
                            className="mt-2 w-full text-sm text-gray-700 border border-gray-200 rounded-lg p-2.5 resize-y focus:outline-none focus:ring-2 focus:ring-teal-400"
                          />
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {finishError && (
                  <div
                    role="alert"
                    data-testid="finish-error"
                    className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 mb-4"
                  >
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
                    <span>{finishError}</span>
                  </div>
                )}

                <div className="text-center">
                  <button
                    onClick={handleFinishInterview}
                    disabled={savingCorrections}
                    className="px-8 py-3 rounded-xl text-white font-medium text-sm disabled:opacity-50 transition-opacity"
                    style={{ backgroundColor: primaryColor }}
                  >
                    {savingCorrections ? 'Saving…' : finishError ? 'Try again' : 'Finish'}
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
              <InterviewerPortrait
                src={interviewerPortraitSrc(
                  branding.interviewer_image_url, branding.interviewer_image_source,
                )}
                name={branding.interviewer_name}
                className="w-24 h-24 rounded-full mb-3 ring-4 ring-white shadow-md"
                textClassName="text-2xl"
              />
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

          {/* The probe's answer, and the only thing that stands between this button and an
              interview. On an engagement that permits the browser's recogniser the probe never
              runs and `speechProbe` stays `unchecked`, which is why the refusal is keyed on the
              one value that means "asked and refused" rather than on "not yet ready". */}
          {speechProbe === 'unavailable' ? (
            <div
              role="alert"
              data-testid="speech-unavailable-notice"
              className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-left text-sm text-amber-900"
            >
              <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>{haltNotice}</span>
            </div>
          ) : (
            <button
              onClick={runInterview}
              disabled={speechProbe === 'checking'}
              className="bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white font-semibold py-3 px-8 rounded-lg text-lg transition-colors"
              style={{ backgroundColor: branding?.primary_color }}
            >
              {speechProbe === 'checking' ? 'Checking your connection…' : 'Start Interview'}
            </button>
          )}
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
  const interviewerImg = interviewerPortraitSrc(
    branding?.interviewer_image_url, branding?.interviewer_image_source,
  )
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
            {/* The centre of the bar, between how far through the questions they are and how
                far through as a percentage - which is where somebody looks to ask "how long
                has this been going?" and found nothing on 17 September. */}
            {startedAt !== null && (
              <ElapsedTime
                startedAt={startedAt}
                timeboxMinutes={scriptTimeboxMinutes(sessionData?.script.sections ?? [])}
              />
            )}
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
            <InterviewerPortrait
              src={interviewerImg}
              name={interviewerName}
              className="w-40 h-40 rounded-full ring-4 ring-teal-400 shadow-2xl"
              textClassName="text-4xl"
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
