import type { EnvBookingSummary } from './bookingRequest'

export type ConflictAck = {
  willing_to_share: boolean | null
  notes: string | null
  acknowledged_by: number | null
  acknowledged_at: string | null
}

export type ConflictItem = {
  other_booking: EnvBookingSummary
  ack: ConflictAck | null
}
