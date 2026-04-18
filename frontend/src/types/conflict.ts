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

export type UserRef = {
  id: number
  username: string
  email: string
}

export type RequestContextRef = {
  id: number
  project_name: string
  notes: string | null
  context_tag: string
  exclusive_use_requested: boolean
  booked_by: UserRef
}

export type ReceivedFeedbackItem = {
  willing_to_share: boolean | null
  notes: string | null
  acknowledged_at: string
  acknowledged_by: UserRef
  source_booking: EnvBookingSummary
  source_request: RequestContextRef
}
