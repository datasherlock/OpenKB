import { useEffect, useState } from "react"
import { useLocation, useNavigate } from "react-router"
import { useTranslation, Trans } from "react-i18next"
import { ArrowRight, Sparkles } from "lucide-react"
import ChatInput, { type SlashCommand } from "@/components/ChatInput"
import { listKbs, getKbPrompts, type KbSummary, type PresetPrompt } from "@/api/kb"
import { cn } from "@/lib/utils"

/** Decorative accent colors, cycled by KB position — the API carries no color. */
const DOTS = ["bg-blue-500", "bg-emerald-500", "bg-amber-500", "bg-violet-500", "bg-rose-500"]
const dotFor = (i: number) => DOTS[i % DOTS.length]

export default function Home() {
  const { t } = useTranslation("home")
  const navigate = useNavigate()
  const location = useLocation() as { state?: { kbId?: string } }
  const [kbs, setKbs] = useState<KbSummary[]>([])
  const [kbId, setKbId] = useState<string>(location.state?.kbId ?? "")
  const [prompts, setPrompts] = useState<PresetPrompt[]>([])

  useEffect(() => {
    let cancelled = false
    listKbs()
      .then((r) => {
        if (cancelled) return
        const list = r.knowledge_bases
        setKbs(list)
        setKbId((prev) => prev || list[0]?.name || "")
      })
      .catch(() => {
        if (!cancelled) setKbs([])
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    if (!kbId) {
      setPrompts([])
      return
    }
    getKbPrompts(kbId)
      .then((p) => {
        if (!cancelled) setPrompts(p)
      })
      .catch(() => {
        if (!cancelled) setPrompts([])
      })
    return () => { cancelled = true }
  }, [kbId])

  const totalDocs = kbs.reduce((a, k) => a + k.document_count, 0)

  const send = (text: string, command: SlashCommand | null) => {
    // A selected command may carry no text (e.g. `/visualize` takes no args).
    if (!kbId || (!text.trim() && !command)) return
    navigate("/chat/new", {
      state: { text, commandId: command?.id ?? null, cmd: command?.cmd ?? null, kbId },
    })
  }

  return (
    <div className="h-full flex flex-col">
      {/* 上方：问候 + 预设提示词（可滚动） */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-[1100px] mx-auto px-6 lg:px-8 pt-[7vh] pb-6">
          <div className="anim-fade-up">
            <h1 className="text-[30px] font-bold tracking-[-0.02em]">{t("greeting")}</h1>
            <p className="mt-1.5 text-[14px] text-muted-foreground">
              <Trans
                t={t}
                i18nKey="ready"
                values={{ docs: totalDocs, kbs: kbs.length }}
                components={[
                  <span className="tabular-nums" />,
                  <span className="tabular-nums" />,
                ]}
              />
            </p>
          </div>

          {prompts.length > 0 && (
            <div className="mt-8 anim-fade-up anim-d2">
              <div className="flex items-center gap-2 text-[12px] font-semibold text-muted-foreground tracking-wide">
                <Sparkles className="w-3.5 h-3.5 text-accent-brand" />
                {t("suggestedPrompts")}
              </div>
              <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {prompts.map((p, i) => (
                  <button
                    key={`${p.prompt}-${i}`}
                    onClick={() => send(p.prompt, null)}
                    className={cn(
                      "group text-left rounded-apple-md glass-2 border border-[hsl(var(--glass-border))] p-4 hover:shadow-glass hover:-translate-y-0.5 hover:border-accent-brand/40 transition-all duration-fast ease-out-apple anim-fade-up cursor-pointer",
                      `anim-d${(i % 4) + 1}`,
                    )}
                  >
                    <div className="text-[14px] font-medium leading-snug line-clamp-3 min-h-[42px] text-foreground/90 group-hover:text-foreground transition-colors">
                      {p.title || p.prompt}
                    </div>
                    {p.description && (
                      <p className="mt-1 text-[12px] text-muted-foreground line-clamp-2">
                        {p.description}
                      </p>
                    )}
                    <div className="mt-3 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
                      <span className={cn("w-1.5 h-1.5 rounded-full", dotFor(0))} />
                      <span>{kbId}</span>
                      <ArrowRight className="w-3.5 h-3.5 ml-auto opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all text-accent-brand" />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 底部：输入框（钉底，斜杠菜单向上弹有干净空间）+ tagline footer */}
      <div className="shrink-0 border-t border-[hsl(var(--glass-border))] glass-2">
        <div className="max-w-[1100px] mx-auto px-6 lg:px-8 pt-2.5 pb-2">
          <ChatInput kbId={kbId} onKbChange={setKbId} onSend={send} autoFocus />
          <p className="mt-2 text-center text-[11px] text-muted-foreground/70">
            {t("tagline")}
          </p>
        </div>
      </div>
    </div>
  )
}
