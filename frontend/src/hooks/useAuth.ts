import { useEffect, useState } from "react"
import { fetchWhoAmI, type WhoAmIResponse } from "@/api/auth"

let cachedAuth: WhoAmIResponse | null = null
let authPromise: Promise<WhoAmIResponse> | null = null

export function getCachedAuth(): WhoAmIResponse | null {
  return cachedAuth
}

export function useAuth() {
  const [auth, setAuth] = useState<WhoAmIResponse | null>(cachedAuth)
  const [loading, setLoading] = useState(!cachedAuth)

  useEffect(() => {
    if (cachedAuth) {
      setAuth(cachedAuth)
      setLoading(false)
      return
    }

    if (!authPromise) {
      authPromise = fetchWhoAmI()
        .then((res) => {
          cachedAuth = res
          return res
        })
        .catch((err) => {
          console.warn("Failed to fetch whoami:", err)
          const fallback: WhoAmIResponse = {
            email: null,
            is_admin: false,
            authenticated: false,
            admin_enforced: false,
          }
          cachedAuth = fallback
          return fallback
        })
    }

    let cancelled = false
    authPromise.then((res) => {
      if (!cancelled) {
        setAuth(res)
        setLoading(false)
      }
    })

    return () => {
      cancelled = true
    }
  }, [])

  return {
    auth,
    loading,
    isAdmin: auth ? auth.is_admin : false,
    email: auth?.email ?? null,
  }
}
