// ui/src/utils/holidays.ts
// Public holiday computation engine.
// All holidays returned as YYYY-MM-DD strings.

export interface PublicHoliday {
  date: string
  name: string
  country: string
}

// ── Easter (Anonymous Gregorian / Meeus/Jones/Butcher algorithm) ──────────────

function easterDate(year: number): Date {
  const a = year % 19
  const b = Math.floor(year / 100)
  const c = year % 100
  const d = Math.floor(b / 4)
  const e = b % 4
  const f = Math.floor((b + 8) / 25)
  const g = Math.floor((b - f + 1) / 3)
  const h = (19 * a + b - d - g + 15) % 30
  const i = Math.floor(c / 4)
  const k = c % 4
  const l = (32 + 2 * e + 2 * i - h - k) % 7
  const m = Math.floor((a + 11 * h + 22 * l) / 451)
  const month = Math.floor((h + l - 7 * m + 114) / 31) - 1  // 0-indexed
  const day   = ((h + l - 7 * m + 114) % 31) + 1
  return new Date(year, month, day)
}

// ── Date helpers ──────────────────────────────────────────────────────────────

function iso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function fixed(year: number, month: number, day: number): string {
  return iso(new Date(year, month - 1, day))
}

function easterOffset(year: number, offsetDays: number): string {
  const e = easterDate(year)
  e.setDate(e.getDate() + offsetDays)
  return iso(e)
}

// nth weekday of a month (1-indexed weekday: 1=Mon…7=Sun per JS getDay mapping below)
function nthWeekday(year: number, month: number, weekday: number, n: number): string {
  // weekday: 0=Sun, 1=Mon, …, 6=Sat
  const first = new Date(year, month - 1, 1)
  let diff = (weekday - first.getDay() + 7) % 7
  diff += (n - 1) * 7
  return iso(new Date(year, month - 1, 1 + diff))
}

// Last weekday of a month
function lastWeekday(year: number, month: number, weekday: number): string {
  const last = new Date(year, month, 0)  // last day of month
  const diff = (last.getDay() - weekday + 7) % 7
  return iso(new Date(year, month - 1, last.getDate() - diff))
}

// Substitute Monday when a fixed holiday falls on a weekend (UK/AU/NZ/CA pattern)
function substituteMonday(year: number, month: number, day: number): string {
  const d = new Date(year, month - 1, day)
  const dow = d.getDay()
  if (dow === 6) d.setDate(d.getDate() + 2)  // Sat → Mon
  if (dow === 0) d.setDate(d.getDate() + 1)  // Sun → Mon
  return iso(d)
}

// ── Country holiday generators ────────────────────────────────────────────────

function holidaysGB(year: number): PublicHoliday[] {
  return [
    { date: substituteMonday(year, 1, 1),  name: "New Year's Day",          country: 'GB' },
    { date: easterOffset(year, -2),         name: 'Good Friday',             country: 'GB' },
    { date: easterOffset(year,  1),         name: 'Easter Monday',           country: 'GB' },
    { date: nthWeekday(year, 5, 1, 1),      name: 'Early May Bank Holiday',  country: 'GB' },
    { date: lastWeekday(year, 5, 1),        name: 'Spring Bank Holiday',     country: 'GB' },
    { date: lastWeekday(year, 8, 1),        name: 'Summer Bank Holiday',     country: 'GB' },
    { date: substituteMonday(year, 12, 25), name: 'Christmas Day',           country: 'GB' },
    { date: substituteMonday(year, 12, 26), name: 'Boxing Day',              country: 'GB' },
  ]
}

function holidaysUS(year: number): PublicHoliday[] {
  return [
    { date: substituteMonday(year, 1, 1),   name: "New Year's Day",      country: 'US' },
    { date: nthWeekday(year,  1, 1, 3),     name: 'Martin Luther King Day', country: 'US' },
    { date: nthWeekday(year,  2, 1, 3),     name: "Presidents' Day",     country: 'US' },
    { date: lastWeekday(year, 5, 1),        name: 'Memorial Day',        country: 'US' },
    { date: substituteMonday(year, 6, 19),  name: 'Juneteenth',          country: 'US' },
    { date: substituteMonday(year, 7, 4),   name: 'Independence Day',    country: 'US' },
    { date: nthWeekday(year,  9, 1, 1),     name: 'Labor Day',           country: 'US' },
    { date: nthWeekday(year, 10, 1, 2),     name: 'Columbus Day',        country: 'US' },
    { date: substituteMonday(year, 11, 11), name: 'Veterans Day',        country: 'US' },
    { date: nthWeekday(year, 11, 4, 4),     name: 'Thanksgiving Day',    country: 'US' },
    { date: substituteMonday(year, 12, 25), name: 'Christmas Day',       country: 'US' },
  ]
}

function holidaysAU(year: number): PublicHoliday[] {
  return [
    { date: substituteMonday(year, 1, 1),  name: "New Year's Day",      country: 'AU' },
    { date: substituteMonday(year, 1, 26), name: 'Australia Day',        country: 'AU' },
    { date: easterOffset(year, -2),        name: 'Good Friday',          country: 'AU' },
    { date: easterOffset(year, -1),        name: 'Easter Saturday',      country: 'AU' },
    { date: easterOffset(year,  1),        name: 'Easter Monday',        country: 'AU' },
    { date: fixed(year, 4, 25),            name: 'ANZAC Day',            country: 'AU' },
    { date: nthWeekday(year, 6, 1, 2),     name: "Queen's Birthday",     country: 'AU' },
    { date: substituteMonday(year, 12, 25),name: 'Christmas Day',        country: 'AU' },
    { date: substituteMonday(year, 12, 26),name: 'Boxing Day',           country: 'AU' },
  ]
}

function holidaysNZ(year: number): PublicHoliday[] {
  return [
    { date: substituteMonday(year, 1, 1),  name: "New Year's Day",       country: 'NZ' },
    { date: substituteMonday(year, 1, 2),  name: "New Year's Day (2)",   country: 'NZ' },
    { date: substituteMonday(year, 2, 6),  name: 'Waitangi Day',         country: 'NZ' },
    { date: easterOffset(year, -2),        name: 'Good Friday',          country: 'NZ' },
    { date: easterOffset(year,  1),        name: 'Easter Monday',        country: 'NZ' },
    { date: fixed(year, 4, 25),            name: 'ANZAC Day',            country: 'NZ' },
    { date: nthWeekday(year, 6, 1, 1),     name: "King's Birthday",      country: 'NZ' },
    { date: nthWeekday(year, 10, 1, 4),    name: 'Labour Day',           country: 'NZ' },
    { date: substituteMonday(year, 12, 25),name: 'Christmas Day',        country: 'NZ' },
    { date: substituteMonday(year, 12, 26),name: 'Boxing Day',           country: 'NZ' },
  ]
}

function holidaysCA(year: number): PublicHoliday[] {
  return [
    { date: substituteMonday(year, 1, 1),  name: "New Year's Day",    country: 'CA' },
    { date: easterOffset(year, -2),        name: 'Good Friday',       country: 'CA' },
    { date: nthWeekday(year, 5, 1, 3),     name: 'Victoria Day',      country: 'CA' },
    { date: substituteMonday(year, 7, 1),  name: 'Canada Day',        country: 'CA' },
    { date: nthWeekday(year, 8, 1, 1),     name: 'Civic Holiday',     country: 'CA' },
    { date: nthWeekday(year, 9, 1, 1),     name: 'Labour Day',        country: 'CA' },
    { date: nthWeekday(year, 10, 1, 2),    name: 'Thanksgiving',      country: 'CA' },
    { date: substituteMonday(year, 11, 11),name: 'Remembrance Day',   country: 'CA' },
    { date: substituteMonday(year, 12, 25),name: 'Christmas Day',     country: 'CA' },
    { date: substituteMonday(year, 12, 26),name: 'Boxing Day',        country: 'CA' },
  ]
}

function holidaysIE(year: number): PublicHoliday[] {
  return [
    { date: substituteMonday(year, 1, 1),  name: "New Year's Day",   country: 'IE' },
    { date: nthWeekday(year, 2, 1, 1),     name: "St. Brigid's Day", country: 'IE' },
    { date: substituteMonday(year, 3, 17), name: "St. Patrick's Day",country: 'IE' },
    { date: easterOffset(year, 1),         name: 'Easter Monday',    country: 'IE' },
    { date: nthWeekday(year, 5, 1, 1),     name: 'May Bank Holiday', country: 'IE' },
    { date: nthWeekday(year, 6, 1, 1),     name: 'June Bank Holiday',country: 'IE' },
    { date: nthWeekday(year, 8, 1, 1),     name: 'August Bank Holiday', country: 'IE' },
    { date: lastWeekday(year, 10, 1),      name: 'October Bank Holiday', country: 'IE' },
    { date: substituteMonday(year, 12, 25),name: 'Christmas Day',    country: 'IE' },
    { date: substituteMonday(year, 12, 26),name: "St. Stephen's Day",country: 'IE' },
  ]
}

function holidaysDE(year: number): PublicHoliday[] {
  return [
    { date: fixed(year, 1, 1),             name: 'Neujahrstag',          country: 'DE' },
    { date: easterOffset(year, -2),        name: 'Karfreitag',           country: 'DE' },
    { date: easterOffset(year,  1),        name: 'Ostermontag',          country: 'DE' },
    { date: fixed(year, 5, 1),             name: 'Tag der Arbeit',       country: 'DE' },
    { date: easterOffset(year, 39),        name: 'Christi Himmelfahrt',  country: 'DE' },
    { date: easterOffset(year, 50),        name: 'Pfingstmontag',        country: 'DE' },
    { date: fixed(year, 10, 3),            name: 'Tag der Deutschen Einheit', country: 'DE' },
    { date: fixed(year, 12, 25),           name: '1. Weihnachtstag',     country: 'DE' },
    { date: fixed(year, 12, 26),           name: '2. Weihnachtstag',     country: 'DE' },
  ]
}

function holidaysFR(year: number): PublicHoliday[] {
  return [
    { date: fixed(year, 1, 1),             name: 'Jour de l\'An',        country: 'FR' },
    { date: easterOffset(year,  1),        name: 'Lundi de Pâques',      country: 'FR' },
    { date: fixed(year, 5, 1),             name: 'Fête du Travail',      country: 'FR' },
    { date: fixed(year, 5, 8),             name: 'Victoire 1945',        country: 'FR' },
    { date: easterOffset(year, 39),        name: 'Ascension',            country: 'FR' },
    { date: easterOffset(year, 50),        name: 'Lundi de Pentecôte',   country: 'FR' },
    { date: fixed(year, 7, 14),            name: 'Fête Nationale',       country: 'FR' },
    { date: fixed(year, 8, 15),            name: 'Assomption',           country: 'FR' },
    { date: fixed(year, 11, 1),            name: 'Toussaint',            country: 'FR' },
    { date: fixed(year, 11, 11),           name: 'Armistice',            country: 'FR' },
    { date: fixed(year, 12, 25),           name: 'Noël',                 country: 'FR' },
  ]
}

function holidaysSG(year: number): PublicHoliday[] {
  return [
    { date: fixed(year, 1, 1),             name: "New Year's Day",   country: 'SG' },
    { date: fixed(year, 5, 1),             name: 'Labour Day',       country: 'SG' },
    { date: fixed(year, 8, 9),             name: 'National Day',     country: 'SG' },
    { date: fixed(year, 12, 25),           name: 'Christmas Day',    country: 'SG' },
    // Note: Hari Raya, Deepavali, Chinese New Year require separate lunar calendar computation
  ]
}

// ── Country metadata ──────────────────────────────────────────────────────────

export const SUPPORTED_LOCALES: { code: string; label: string; bcp47: string }[] = [
  { code: 'GB', label: 'United Kingdom', bcp47: 'en-GB' },
  { code: 'US', label: 'United States',  bcp47: 'en-US' },
  { code: 'AU', label: 'Australia',      bcp47: 'en-AU' },
  { code: 'NZ', label: 'New Zealand',    bcp47: 'en-NZ' },
  { code: 'CA', label: 'Canada',         bcp47: 'en-CA' },
  { code: 'IE', label: 'Ireland',        bcp47: 'en-IE' },
  { code: 'DE', label: 'Germany',        bcp47: 'de-DE' },
  { code: 'FR', label: 'France',         bcp47: 'fr-FR' },
  { code: 'SG', label: 'Singapore',      bcp47: 'en-SG' },
]

const GENERATORS: Record<string, (year: number) => PublicHoliday[]> = {
  GB: holidaysGB,
  US: holidaysUS,
  AU: holidaysAU,
  NZ: holidaysNZ,
  CA: holidaysCA,
  IE: holidaysIE,
  DE: holidaysDE,
  FR: holidaysFR,
  SG: holidaysSG,
}

// ── Public API ────────────────────────────────────────────────────────────────

export function bcp47(countryCode: string): string {
  return SUPPORTED_LOCALES.find(l => l.code === countryCode)?.bcp47 ?? 'en-GB'
}

export function formatDate(dateStr: string, countryCode: string): string {
  if (!dateStr) return ''
  const locale = bcp47(countryCode)
  return new Intl.DateTimeFormat(locale, {
    day: '2-digit', month: '2-digit', year: 'numeric',
  }).format(new Date(dateStr + 'T00:00:00'))
}

export function formatDateShort(dateStr: string, countryCode: string): string {
  if (!dateStr) return ''
  const locale = bcp47(countryCode)
  return new Intl.DateTimeFormat(locale, {
    day: '2-digit', month: '2-digit',
  }).format(new Date(dateStr + 'T00:00:00'))
}

/** Return all public holidays for a country between two YYYY-MM-DD dates (inclusive). */
export function getPublicHolidays(
  countryCode: string,
  fromDate: string,
  toDate: string,
): PublicHoliday[] {
  // Accept both country code ('GB') and BCP47 ('en-GB')
  const code = countryCode.includes('-')
    ? countryCode.split('-').pop()!.toUpperCase()
    : countryCode.toUpperCase()
  const gen = GENERATORS[code]
  if (!gen) return []
  const fromYear = parseInt(fromDate.slice(0, 4))
  const toYear   = parseInt(toDate.slice(0, 4))
  const result: PublicHoliday[] = []
  for (let y = fromYear; y <= toYear; y++) {
    for (const h of gen(y)) {
      if (h.date >= fromDate && h.date <= toDate) result.push(h)
    }
  }
  return result.sort((a, b) => a.date.localeCompare(b.date))
}

/** Build a Set of all non-working date strings (weekends + holidays + custom ranges). */
export function buildExcludedDateSet(
  holidays: PublicHoliday[],
  nonWorkingRanges: { start_date: string; end_date: string }[],
): Set<string> {
  const excluded = new Set<string>()
  for (const h of holidays) excluded.add(h.date)
  for (const r of nonWorkingRanges) {
    const cur = new Date(r.start_date + 'T00:00:00')
    const end = new Date(r.end_date   + 'T00:00:00')
    while (cur <= end) {
      excluded.add(iso(cur))
      cur.setDate(cur.getDate() + 1)
    }
  }
  return excluded
}

/** Count Mon-Fri working days between two dates, excluding holidays and custom ranges. */
export function workingDaysBetween(
  from: string,
  to: string,
  excluded?: Set<string>,
): number {
  if (from >= to) return 0
  const end = new Date(to + 'T00:00:00')
  const cur = new Date(from + 'T00:00:00')
  cur.setDate(cur.getDate() + 1)
  let count = 0
  while (cur <= end) {
    const dow = cur.getDay()
    const ds  = iso(cur)
    if (dow !== 0 && dow !== 6 && (!excluded || !excluded.has(ds))) count++
    cur.setDate(cur.getDate() + 1)
  }
  return count
}
