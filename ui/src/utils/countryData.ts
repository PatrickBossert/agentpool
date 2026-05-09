// ui/src/utils/countryData.ts
// Static mapping of ISO 3166-1 alpha-2 country codes to timezone, currency, and language.
// For multi-timezone countries, the most common business timezone is used as the default.

export interface CountryInfo {
  name: string
  timezone: string  // IANA tz identifier
  currency: string  // ISO 4217 code
  language: string  // primary business language
}

export const COUNTRY_DATA: Record<string, CountryInfo> = {
  // Europe
  AT: { name: 'Austria', timezone: 'Europe/Vienna', currency: 'EUR', language: 'German' },
  BE: { name: 'Belgium', timezone: 'Europe/Brussels', currency: 'EUR', language: 'Dutch' },
  BG: { name: 'Bulgaria', timezone: 'Europe/Sofia', currency: 'BGN', language: 'Bulgarian' },
  CH: { name: 'Switzerland', timezone: 'Europe/Zurich', currency: 'CHF', language: 'German' },
  CY: { name: 'Cyprus', timezone: 'Asia/Nicosia', currency: 'EUR', language: 'Greek' },
  CZ: { name: 'Czech Republic', timezone: 'Europe/Prague', currency: 'CZK', language: 'Czech' },
  DE: { name: 'Germany', timezone: 'Europe/Berlin', currency: 'EUR', language: 'German' },
  DK: { name: 'Denmark', timezone: 'Europe/Copenhagen', currency: 'DKK', language: 'Danish' },
  EE: { name: 'Estonia', timezone: 'Europe/Tallinn', currency: 'EUR', language: 'Estonian' },
  ES: { name: 'Spain', timezone: 'Europe/Madrid', currency: 'EUR', language: 'Spanish' },
  FI: { name: 'Finland', timezone: 'Europe/Helsinki', currency: 'EUR', language: 'Finnish' },
  FR: { name: 'France', timezone: 'Europe/Paris', currency: 'EUR', language: 'French' },
  GB: { name: 'United Kingdom', timezone: 'Europe/London', currency: 'GBP', language: 'English' },
  GR: { name: 'Greece', timezone: 'Europe/Athens', currency: 'EUR', language: 'Greek' },
  HR: { name: 'Croatia', timezone: 'Europe/Zagreb', currency: 'EUR', language: 'Croatian' },
  HU: { name: 'Hungary', timezone: 'Europe/Budapest', currency: 'HUF', language: 'Hungarian' },
  IE: { name: 'Ireland', timezone: 'Europe/Dublin', currency: 'EUR', language: 'English' },
  IS: { name: 'Iceland', timezone: 'Atlantic/Reykjavik', currency: 'ISK', language: 'Icelandic' },
  IT: { name: 'Italy', timezone: 'Europe/Rome', currency: 'EUR', language: 'Italian' },
  LT: { name: 'Lithuania', timezone: 'Europe/Vilnius', currency: 'EUR', language: 'Lithuanian' },
  LU: { name: 'Luxembourg', timezone: 'Europe/Luxembourg', currency: 'EUR', language: 'French' },
  LV: { name: 'Latvia', timezone: 'Europe/Riga', currency: 'EUR', language: 'Latvian' },
  MT: { name: 'Malta', timezone: 'Europe/Malta', currency: 'EUR', language: 'English' },
  NL: { name: 'Netherlands', timezone: 'Europe/Amsterdam', currency: 'EUR', language: 'Dutch' },
  NO: { name: 'Norway', timezone: 'Europe/Oslo', currency: 'NOK', language: 'Norwegian' },
  PL: { name: 'Poland', timezone: 'Europe/Warsaw', currency: 'PLN', language: 'Polish' },
  PT: { name: 'Portugal', timezone: 'Europe/Lisbon', currency: 'EUR', language: 'Portuguese' },
  RO: { name: 'Romania', timezone: 'Europe/Bucharest', currency: 'RON', language: 'Romanian' },
  SE: { name: 'Sweden', timezone: 'Europe/Stockholm', currency: 'SEK', language: 'Swedish' },
  SI: { name: 'Slovenia', timezone: 'Europe/Ljubljana', currency: 'EUR', language: 'Slovenian' },
  SK: { name: 'Slovakia', timezone: 'Europe/Bratislava', currency: 'EUR', language: 'Slovak' },
  // Americas
  AR: { name: 'Argentina', timezone: 'America/Argentina/Buenos_Aires', currency: 'ARS', language: 'Spanish' },
  BR: { name: 'Brazil', timezone: 'America/Sao_Paulo', currency: 'BRL', language: 'Portuguese' },
  CA: { name: 'Canada', timezone: 'America/Toronto', currency: 'CAD', language: 'English' },
  CL: { name: 'Chile', timezone: 'America/Santiago', currency: 'CLP', language: 'Spanish' },
  CO: { name: 'Colombia', timezone: 'America/Bogota', currency: 'COP', language: 'Spanish' },
  MX: { name: 'Mexico', timezone: 'America/Mexico_City', currency: 'MXN', language: 'Spanish' },
  PE: { name: 'Peru', timezone: 'America/Lima', currency: 'PEN', language: 'Spanish' },
  US: { name: 'United States', timezone: 'America/New_York', currency: 'USD', language: 'English' },
  // Asia Pacific
  AU: { name: 'Australia', timezone: 'Australia/Sydney', currency: 'AUD', language: 'English' },
  CN: { name: 'China', timezone: 'Asia/Shanghai', currency: 'CNY', language: 'Mandarin' },
  HK: { name: 'Hong Kong', timezone: 'Asia/Hong_Kong', currency: 'HKD', language: 'English' },
  ID: { name: 'Indonesia', timezone: 'Asia/Jakarta', currency: 'IDR', language: 'Indonesian' },
  IN: { name: 'India', timezone: 'Asia/Kolkata', currency: 'INR', language: 'English' },
  JP: { name: 'Japan', timezone: 'Asia/Tokyo', currency: 'JPY', language: 'Japanese' },
  KR: { name: 'South Korea', timezone: 'Asia/Seoul', currency: 'KRW', language: 'Korean' },
  MY: { name: 'Malaysia', timezone: 'Asia/Kuala_Lumpur', currency: 'MYR', language: 'English' },
  NZ: { name: 'New Zealand', timezone: 'Pacific/Auckland', currency: 'NZD', language: 'English' },
  PH: { name: 'Philippines', timezone: 'Asia/Manila', currency: 'PHP', language: 'English' },
  SG: { name: 'Singapore', timezone: 'Asia/Singapore', currency: 'SGD', language: 'English' },
  TH: { name: 'Thailand', timezone: 'Asia/Bangkok', currency: 'THB', language: 'Thai' },
  TW: { name: 'Taiwan', timezone: 'Asia/Taipei', currency: 'TWD', language: 'Mandarin' },
  VN: { name: 'Vietnam', timezone: 'Asia/Ho_Chi_Minh', currency: 'VND', language: 'Vietnamese' },
  // Middle East & Africa
  AE: { name: 'United Arab Emirates', timezone: 'Asia/Dubai', currency: 'AED', language: 'Arabic' },
  EG: { name: 'Egypt', timezone: 'Africa/Cairo', currency: 'EGP', language: 'Arabic' },
  IL: { name: 'Israel', timezone: 'Asia/Jerusalem', currency: 'ILS', language: 'Hebrew' },
  KE: { name: 'Kenya', timezone: 'Africa/Nairobi', currency: 'KES', language: 'English' },
  NG: { name: 'Nigeria', timezone: 'Africa/Lagos', currency: 'NGN', language: 'English' },
  SA: { name: 'Saudi Arabia', timezone: 'Asia/Riyadh', currency: 'SAR', language: 'Arabic' },
  TR: { name: 'Turkey', timezone: 'Europe/Istanbul', currency: 'TRY', language: 'Turkish' },
  ZA: { name: 'South Africa', timezone: 'Africa/Johannesburg', currency: 'ZAR', language: 'English' },
}

export const COUNTRY_OPTIONS = Object.entries(COUNTRY_DATA)
  .map(([code, info]) => ({ code, name: info.name }))
  .sort((a, b) => a.name.localeCompare(b.name))
