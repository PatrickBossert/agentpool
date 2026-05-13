// Maps language_countryCode → ElevenLabs voice ID
const VOICE_LOCALE_MAP: Record<string, string> = {
  'en_GB': '21m00Tcm4TlvDq8ikWAM', // Rachel
  'en_US': 'EXAVITQu4vr4xnSDxMaL', // Bella
  'en_AU': 'AZnzlk1XvdvUeBnXmlld', // Domi
  'en_NZ': 'MF3mGyEYCl7XYWbV9V6O', // Elli
  'en_CA': 'TxGEqnHWrfWFTfGW9XjX', // Josh
  'fr_FR': 'VR6AewLTigWG4xSOukaG', // Arnold
  'de_DE': 'pNInz6obpgDQGcFmaJgB', // Adam
  'es_ES': 'yoZ06aMxZJJ28mfd3POQ', // Sam
}

const DEFAULT_VOICE_ID = '21m00Tcm4TlvDq8ikWAM' // Rachel (en/GB)

export function getVoiceId(language: string, countryCode: string): string {
  const key = `${language}_${countryCode}`
  return VOICE_LOCALE_MAP[key] ?? DEFAULT_VOICE_ID
}
