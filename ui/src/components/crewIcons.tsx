// Lucide SVG icon components mapped to crew keys.
// Kept in a .tsx file so agentStatus.ts (pure TS) stays JSX-free.
import {
  Network, ClipboardList, Search, Users, Mic,
  Sparkles, Building2, MapPin, TrendingUp,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export const CREW_ICON_COMPONENT: Record<string, LucideIcon> = {
  discovery_mapping:      Network,
  assessment_design:      ClipboardList,
  discovery:              Search,
  stakeholder_management: Users,
  discovery_interviews:   Mic,
  value_design:           Sparkles,
  architecture:           Building2,
  delivery:               MapPin,
  business_plan:          TrendingUp,
}
