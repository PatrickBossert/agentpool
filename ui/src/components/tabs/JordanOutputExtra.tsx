// ui/src/components/tabs/JordanOutputExtra.tsx
//
// Jordan's Output tab extra: what participants have written back.
//
// It sits here rather than on the Stakeholders page because the correspondent owns the
// conversation. Engagement mail leaves over Jordan's name and Jordan's address - one mailbox
// per role, see api/services/outbound_mail.py - so the replies to it are read on the
// stakeholder manager's surface, next to the engagement plan they are about. The roster is a
// list of people; this is a list of things somebody said.
//
// The unread count is the point of the panel. A reply nobody sees is a reply lost, and the
// endpoint that receives one is silent by design - it answers the provider identically
// whether it stored a reply or dropped an unroutable one, so nothing about the arrival is
// visible anywhere else.
//
// `body` is rendered as text and never as markup. It arrived through an unauthenticated
// webhook; the server stores plain text for exactly this reason, and this component must not
// be the place that undoes it.
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { Mail, MailOpen, Paperclip, Scissors } from 'lucide-react'
import { inboundRepliesApi } from '../../api/endpoints'
import type { InboundReply } from '../../types'

function receivedLabel(value: string): string {
  // The server writes SQLite's CURRENT_TIMESTAMP, which is UTC with no zone marker. Parsed
  // naively it reads as local time and a reply that arrived an hour ago is dated tomorrow.
  const parsed = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function ReplyCard({ slug, reply }: { slug: string; reply: InboundReply }) {
  const qc = useQueryClient()
  const markRead = useMutation({
    mutationFn: () => inboundRepliesApi.markRead(slug, reply.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['inbound-replies', slug] }) },
  })
  const unread = reply.read_at === null

  return (
    <div
      className={`rounded-lg border px-3 py-2.5 ${
        unread ? 'border-brand/30 bg-brand/5' : 'border-gray-100 bg-white'
      }`}
    >
      <div className="flex items-start gap-2">
        <span className={unread ? 'text-brand' : 'text-gray-300'} aria-hidden="true">
          {unread ? <Mail size={13} /> : <MailOpen size={13} />}
        </span>
        <div className="flex-1 min-w-0">
          {/*
            The author is the address the message came from, and the stakeholder is the
            thread it routed to. Those are two different facts and the heading used to show
            only the second, which reads as "this client individual said this" for a message
            anybody holding the address could have sent - including the operator, since
            dev_mode holds participant mail at DEV_MODE_ADDRESS with the participant's live
            token on it. The sender leads; the thread is stated underneath.
          */}
          <p className="text-xs font-medium text-gray-800 truncate">
            {reply.from_address || 'Unknown sender'}
          </p>
          <p className="text-[11px] text-gray-500 truncate">
            Reply on {reply.stakeholder_name || 'an unknown participant'}&apos;s thread
          </p>
          {!reply.sender_confirmed && (
            <p className="mt-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
              Not {reply.stakeholder_name || 'that participant'}&apos;s address on file -
              routed by reply token, so the author is not confirmed
            </p>
          )}
          <p className="mt-1 text-[11px] text-gray-500 truncate">
            {reply.subject || '(no subject)'}
          </p>
          <p className="mt-1.5 text-xs text-gray-700 whitespace-pre-wrap break-words">
            {reply.body || '(no text content)'}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[10px] text-gray-400">
            <span>{receivedLabel(reply.received_at)}</span>
            {reply.attachment_count > 0 && (
              <span className="flex items-center gap-1">
                <Paperclip size={10} />
                {reply.attachment_count} attachment{reply.attachment_count === 1 ? '' : 's'} - not
                stored, ask the sender
              </span>
            )}
            {reply.truncated && (
              <span className="flex items-center gap-1">
                <Scissors size={10} />
                Shortened - the whole message is in the mailbox
              </span>
            )}
          </div>
        </div>
        {unread && (
          <button
            type="button"
            onClick={() => markRead.mutate()}
            disabled={markRead.isPending}
            className="text-[10px] font-medium text-brand hover:underline disabled:opacity-50"
          >
            Mark read
          </button>
        )}
      </div>
    </div>
  )
}

export default function JordanOutputExtra({ slug }: { slug: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['inbound-replies', slug],
    queryFn: () => inboundRepliesApi.list(slug),
    refetchInterval: 60_000,
  })

  if (isLoading) {
    return <p className="text-xs text-gray-400 py-3 animate-pulse">Loading replies…</p>
  }

  // Said rather than shown as an empty list. "No replies yet" over a failed request is the
  // reassuring lie - it looks exactly like a quiet inbox.
  if (isError) {
    return (
      <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-6 text-center">
        <p className="text-xs text-gray-400">Replies could not be loaded.</p>
      </div>
    )
  }

  const replies = data?.replies ?? []

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
          Participant replies
        </p>
        {(data?.unread ?? 0) > 0 && (
          <span className="rounded-full bg-brand/10 px-2 py-0.5 text-[10px] font-medium text-teal-700">
            {data?.unread} unread
          </span>
        )}
      </div>

      {replies.length === 0 ? (
        <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-6 text-center">
          <p className="text-xs text-gray-400">
            No replies yet. A participant who answers one of Jordan&apos;s messages arrives here.
          </p>
        </div>
      ) : (
        <div className="space-y-1.5 max-h-96 overflow-y-auto">
          {replies.map((reply) => (
            <ReplyCard key={reply.id} slug={slug} reply={reply} />
          ))}
        </div>
      )}
    </div>
  )
}
