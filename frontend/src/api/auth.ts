import { apiFetch } from "./client"

export interface WhoAmIResponse {
  email: string | null
  is_admin: boolean
  authenticated: boolean
  admin_enforced: boolean
}

export async function fetchWhoAmI(): Promise<WhoAmIResponse> {
  return apiFetch<WhoAmIResponse>("/api/v1/auth/whoami")
}
