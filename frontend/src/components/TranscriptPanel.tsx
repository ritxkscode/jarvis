
import { useStore } from '../lib/store'

interface TranscriptEntry {
  id: string
  role: 'user' | 'jarvis' | 'system'
  text: string
  timestamp: Date
}

interface TranscriptPanelProps {
  transcripts: TranscriptEntry[]
  onClear: () => void
}

export function TranscriptPanel({ transcripts, onClear }: TranscriptPanelProps) {
  const { showTranscript } = useStore()

  if (!showTranscript || transcripts.length === 0) return null

  return (
    <div className="hud-transcript">
      <div className="transcript-panel">
        <div className="transcript-header">
          <span>TRANSCRIPT</span>
          <button
            onClick={onClear}
            style={{
              background: 'none',
              border: '1px solid var(--border)',
              color: 'var(--fg-muted)',
              padding: '0.25rem 0.5rem',
              borderRadius: '3px',
              fontSize: '0.65rem',
              cursor: 'pointer',
              fontFamily: "'Orbitron', sans-serif",
            }}
          >
            CLEAR
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
          {transcripts.map((entry) => (
            <div key={entry.id} className="transcript-entry">
              <span className={`transcript-role ${entry.role}`}>
                {entry.role === 'user' ? 'USER' : entry.role === 'jarvis' ? 'JARVIS' : 'SYS'}
              </span>
              <span className="transcript-text">{entry.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}