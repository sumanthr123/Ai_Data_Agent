import { MessageSquare, SquarePen, Trash2 } from 'lucide-react'
import { cn } from '../lib/cn'
import type { Chat } from '../hooks/useConsensusStream'

const DAY = 86_400_000

function bucket(ts: number): string {
  const startOfToday = new Date().setHours(0, 0, 0, 0)
  if (ts >= startOfToday) return 'Today'
  if (ts >= startOfToday - DAY) return 'Yesterday'
  if (ts >= startOfToday - 7 * DAY) return 'Previous 7 days'
  return 'Older'
}

export function ChatSidebar({ chats, activeId, onSelect, onNew, onDelete }: {
  chats: Chat[]; activeId: string | null; onSelect: (id: string) => void; onNew: () => void; onDelete: (id: string) => void
}) {
  const groups = chats.reduce<[string, Chat[]][]>((acc, chat) => {
    const label = bucket(chat.updatedAt)
    const last = acc.at(-1)
    if (last && last[0] === label) last[1].push(chat)
    else acc.push([label, [chat]])
    return acc
  }, [])

  return (
    <div className="flex h-full flex-col">
      <div className="p-3">
        <button type="button" onClick={onNew}
          className={cn('flex w-full items-center gap-2 rounded-xl border px-3 py-2.5 text-[13.5px] font-medium transition',
            activeId === null ? 'border-sky-400/40 bg-sky-400/10 text-white' : 'border-white/10 text-slate-200 hover:bg-white/[0.05]')}>
          <SquarePen className="h-4 w-4" /> New chat
        </button>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4" aria-label="Chats">
        {chats.length === 0 && <p className="px-3 py-2 text-[12.5px] text-slate-400">Your chats will appear here.</p>}
        {groups.map(([label, items]) => (
          <div key={label} className="mb-3">
            <div className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">{label}</div>
            {items.map((chat) => (
              <div key={chat.id} className={cn('group flex items-center rounded-lg', chat.id === activeId ? 'bg-white/[0.08]' : 'hover:bg-white/[0.04]')}>
                <button type="button" onClick={() => onSelect(chat.id)} title={chat.title} aria-current={chat.id === activeId}
                  className={cn('flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-[13px]', chat.id === activeId ? 'text-white' : 'text-slate-300')}>
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                  <span className="truncate">{chat.title}</span>
                </button>
                <button type="button" onClick={() => { if (confirm(`Delete "${chat.title}"?`)) onDelete(chat.id) }} aria-label={`Delete ${chat.title}`}
                  className="mr-1 rounded-md p-1.5 text-slate-400 opacity-0 hover:bg-white/10 hover:text-rose-300 focus:opacity-100 group-hover:opacity-100">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        ))}
      </nav>
    </div>
  )
}
