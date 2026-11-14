import { useState, useEffect } from 'react'
import { Reactor } from './ui/Reactor'
import { BootSequence } from './ui/BootSequence'
import { TranscriptPanel } from './components/TranscriptPanel'
import { SidePanels } from './components/SidePanels'
import { ControlsHint } from './components/ControlsHint'
import { DiagnosticsModal } from './components/DiagnosticsModal'
import { AudioTest } from './components/AudioTest'
import { useBridge } from './hooks/useBridge'
import { useVoice } from './hooks/useVoice'
import { useStore } from './lib/store'

export function App() {
  const [bootComplete, setBootComplete] = useState(false)
  const [showDiagnostics, setShowDiagnostics] = useState(false)
  const [showAudioTest, setShowAudioTest] = useState(false)
  const [initialized, setInitialized] = useState(false)

  const {
    connected,
    connect,
    sendMessage,
    transcripts,
    clearTranscripts,
  } = useBridge()

  const {
    listening,
    startListening,
    stopListening,
    speak,
    supported,
  } = useVoice({
    onTranscript: (text, isFinal) => {
      if (isFinal && text.trim()) {
        sendMessage({ type: 'voice', action: 'stop', audio: '' })
        sendMessage({ type: 'chat', text })
      }
    },
    onError: (err) => console.error('Voice error:', err),
  })

  const { setStatus } = useStore()

  // Initialize on mount
  useEffect(() => {
    const timer = setTimeout(() => {
      setBootComplete(true)
      // Auto-connect to bridge
      connect()
    }, 3000)
    return () => clearTimeout(timer)
  }, [connect])

  // Handle connection status
  useEffect(() => {
    setStatus(connected ? 'connected' : 'disconnected')
  }, [connected, setStatus])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

      switch (e.key) {
        case ' ':
          e.preventDefault()
          if (!listening) startListening()
          break
        case 'Escape':
          stopListening()
          speak('Standing down')
          break
        case 'v':
        case 'V':
          // Cycle voice - handled by browser
          break
        case 'd':
        case 'D':
          setShowDiagnostics(!showDiagnostics)
          break
        case 't':
        case 'T':
          setShowAudioTest(!showAudioTest)
          // Play test sound
          const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+DyvmwhBSuBzvLZiTYIG2m98OScTgwOUarm7blmGgU7k9n1unEiBC13yO/eizEIHWq+8+OWT')
          audio.play().catch(() => {})
          break
        case '~':
        case '`':
          if (!initialized) {
            setInitialized(true)
            startListening()
            speak('Systems initialized. Jarvis online.')
          }
          break
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [connected, listening, startListening, stopListening, speak, showDiagnostics, setShowDiagnostics, showAudioTest, setShowAudioTest, initialized])

  return (
    <>
      {/* Three.js Reactor */}
      <Reactor
        intensity={listening ? 1.5 : 0.5}
        color={listening ? '#00ff88' : '#00d4ff'}
        style={listening ? 'sphere' : 'ring'}
        scale={listening ? 1.2 : 1}
      />

      {/* HUD Overlay */}
      <div className="hud-overlay">
        {/* Top Bar */}
        <div className="hud-top-bar">
          <div className="hud-logo">J.A.R.V.I.S.</div>
          <div className="hud-status">
            <div className="hud-status-item">
              <span className={`hud-dot ${connected ? 'connected' : ''}`}></span>
              <span>{connected ? 'BRIDGE ONLINE' : 'BRIDGE OFFLINE'}</span>
            </div>
            <div className="hud-status-item">
              <span className={`hud-dot ${listening ? 'connected' : ''}`}></span>
              <span>{listening ? 'LISTENING' : 'STANDBY'}</span>
            </div>
            <div className="hud-status-item">
              <span className="hud-dot"></span>
              <span>MODEL: CLAUDE-OPUS-5</span>
            </div>
          </div>
        </div>

        {/* Boot Sequence */}
        {!bootComplete && (
          <BootSequence onComplete={setBootComplete} />
        )}

        {/* Main Interface */}
        {bootComplete && !initialized && (
          <div className="hud-center">
            <button
              className="init-button"
              onClick={() => {
                setInitialized(true)
                startListening()
                speak('Systems initialized. Jarvis online.')
              }}
            >
              <span>INITIALISE</span>
              <span className="key-hint">Click or press ~</span>
            </button>
          </div>
        )}

        {bootComplete && initialized && (
          <>
            {/* Transcript Panel */}
            <TranscriptPanel
              transcripts={transcripts}
              onClear={clearTranscripts}
            />

            {/* Side Panels */}
            <SidePanels connected={connected} listening={listening} />

            {/* Controls Hint */}
            <ControlsHint />

            {/* Diagnostics Modal */}
            {showDiagnostics && (
              <DiagnosticsModal
                onClose={() => setShowDiagnostics(false)}
                connected={connected}
                listening={listening}
                voiceSupported={supported}
              />
            )}

            {/* Audio Test */}
            {showAudioTest && (
              <AudioTest onClose={() => setShowAudioTest(false)} />
            )}
          </>
        )}
      </div>
    </>
  )
}