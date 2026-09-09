import { useEffect, useRef, useState } from "react"
import { useLocation } from "react-router"
import { useTranslation } from "react-i18next"
import { Waypoints, RefreshCw, ExternalLink, Maximize2, Minimize2, Loader2, ChevronDown } from "lucide-react"
import { toast } from "sonner"
import { listKbs, type KbSummary } from "@/api/kb"
import { getGraphBlobUrl } from "@/api/artifacts"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

export default function GraphView() {
  const { t } = useTranslation(["common", "chat", "artifacts"])
  const location = useLocation() as { state?: { kbId?: string } }
  const [kbs, setKbs] = useState<KbSummary[]>([])
  const [kbId, setKbId] = useState<string>(location.state?.kbId ?? "")
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const currentBlobRef = useRef<string | null>(null)

  // Load KBs list
  useEffect(() => {
    let cancelled = false
    listKbs()
      .then((r) => {
        if (cancelled) return
        const list = r.knowledge_bases
        setKbs(list)
        setKbId((prev) => prev || list[0]?.name || "lbg-wiki")
      })
      .catch(() => {
        if (!cancelled) setKbId("lbg-wiki")
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Load graph HTML as blob URL when kbId changes
  const loadGraph = (targetKb: string) => {
    if (!targetKb) return
    setLoading(true)
    setError(null)
    getGraphBlobUrl(targetKb)
      .then((url) => {
        if (currentBlobRef.current) {
          URL.revokeObjectURL(currentBlobRef.current)
        }
        currentBlobRef.current = url
        setBlobUrl(url)
        setLoading(false)
      })
      .catch((err) => {
        console.error("Failed to load graph:", err)
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
        toast.error(t("common:errors.requestFailed"))
      })
  }

  useEffect(() => {
    if (kbId) {
      loadGraph(kbId)
    }
    return () => {
      if (currentBlobRef.current) {
        URL.revokeObjectURL(currentBlobRef.current)
        currentBlobRef.current = null
      }
    }
  }, [kbId])

  const toggleFullscreen = () => {
    if (!containerRef.current) return
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {})
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {})
    }
  }

  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement)
    }
    document.addEventListener("fullscreenchange", handleFsChange)
    return () => document.removeEventListener("fullscreenchange", handleFsChange)
  }, [])

  return (
    <div ref={containerRef} className="relative h-full w-full flex flex-col bg-[#080b11] overflow-hidden">
      {/* Top Floating Glass Header */}
      <div className="absolute top-3 left-4 z-20 flex items-center gap-2 pointer-events-auto">
        <div className="flex items-center gap-2 rounded-apple-md glass-2 px-3 py-1.5 border border-[hsl(var(--glass-border))] shadow-glass">
          <Waypoints className="w-4 h-4 text-accent-brand" />
          <span className="text-[13.5px] font-semibold tracking-tight text-foreground">
            {t("common:nav.graph")}
          </span>

          {kbs.length > 1 ? (
            <DropdownMenu>
              <DropdownMenuTrigger className="flex items-center gap-1 ml-1 px-2 py-0.5 rounded-apple-xs text-[12px] font-mono2 bg-accent/40 hover:bg-accent/80 transition-colors">
                <span>{kbId}</span>
                <ChevronDown className="w-3 h-3 opacity-60" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-[140px]">
                {kbs.map((k) => (
                  <DropdownMenuItem
                    key={k.name}
                    onClick={() => setKbId(k.name)}
                    className={cn(k.name === kbId && "font-semibold text-accent-brand")}
                  >
                    {k.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <span className="text-[12px] font-mono2 text-muted-foreground ml-1">
              {kbId}
            </span>
          )}
        </div>

        {/* Action buttons */}
        <button
          onClick={() => loadGraph(kbId)}
          disabled={loading}
          title={t("common:actions.refresh")}
          className="grid h-8 w-8 place-items-center rounded-apple-md glass-2 border border-[hsl(var(--glass-border))] text-muted-foreground hover:text-foreground transition-all duration-fast shadow-glass hover:scale-105 active:scale-95 disabled:opacity-50"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
        </button>

        {blobUrl && (
          <button
            onClick={() => window.open(blobUrl, "_blank")}
            title={t("artifacts:panel.openTab")}
            className="grid h-8 w-8 place-items-center rounded-apple-md glass-2 border border-[hsl(var(--glass-border))] text-muted-foreground hover:text-foreground transition-all duration-fast shadow-glass hover:scale-105 active:scale-95"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
        )}

        <button
          onClick={toggleFullscreen}
          title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
          className="grid h-8 w-8 place-items-center rounded-apple-md glass-2 border border-[hsl(var(--glass-border))] text-muted-foreground hover:text-foreground transition-all duration-fast shadow-glass hover:scale-105 active:scale-95"
        >
          {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Main Graph Iframe View */}
      <div className="relative flex-1 min-h-0 w-full h-full">
        {loading && (
          <div className="absolute inset-0 z-10 grid place-items-center bg-[#080b11]/80 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-7 h-7 animate-spin text-accent-brand" />
              <p className="text-[13px] text-muted-foreground font-medium">
                {t("common:loading")}
              </p>
            </div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 z-10 grid place-items-center bg-[#080b11]/90">
            <div className="text-center p-6 max-w-md rounded-apple-lg glass-2 border border-destructive/30">
              <p className="text-[14px] text-destructive font-medium mb-3">{error}</p>
              <button
                onClick={() => loadGraph(kbId)}
                className="px-4 py-1.5 rounded-apple-sm bg-accent-brand text-white text-[13px] font-medium hover:opacity-90 transition-opacity"
              >
                {t("common:actions.refresh")}
              </button>
            </div>
          </div>
        )}

        {blobUrl && (
          <iframe
            key={blobUrl}
            src={blobUrl}
            title="Knowledge Graph"
            className="h-full w-full border-0 bg-[#080b11]"
            sandbox="allow-scripts allow-same-origin allow-popups"
          />
        )}
      </div>
    </div>
  )
}
