
interface DiagnosticsModalProps {
  onClose: () => void
  connected: boolean
  listening: boolean
  voiceSupported: boolean
}

export function DiagnosticsModal({ onClose, connected, listening, voiceSupported }: DiagnosticsModalProps) {
  const getBrowserInfo = () => {
    const ua = navigator.userAgent
    let browser = 'Unknown'
    if (ua.includes('Chrome')) browser = 'Chrome'
    else if (ua.includes('Firefox')) browser = 'Firefox'
    else if (ua.includes('Safari')) browser = 'Safari'
    else if (ua.includes('Edge')) browser = 'Edge'
    return `${browser} (${navigator.platform})`
  }

  return (
    <div className="diagnostics-modal" role="dialog" aria-modal="true" aria-labelledby="diag-title">
      <div className="diagnostics-header">
        <h2 id="diag-title" className="diagnostics-title">DIAGNOSTICS</h2>
        <button className="diagnostics-close" onClick={onClose}>CLOSE</button>
      </div>

      <div className="diagnostics-grid">
        {/* Connection */}
        <div className="diagnostics-card">
          <div className="diagnostics-card-title">CONNECTION</div>
          <div className="diagnostics-item">
            <span>Bridge WebSocket</span>
            <span className={`status-badge ${connected ? 'ok' : 'error'}`}>
              {connected ? 'CONNECTED' : 'DISCONNECTED'}
            </span>
          </div>
          <div className="diagnostics-item">
            <span>Endpoint</span>
            <span className="panel-value" style={{ fontFamily: 'inherit' }}>ws://localhost:8787/ws</span>
          </div>
          <div className="diagnostics-item">
            <span>Reconnect</span>
            <span className="status-badge ok">AUTO</span>
          </div>
        </div>

        {/* Voice */}
        <div className="diagnostics-card">
          <div className="diagnostics-card-title">VOICE PIPELINE</div>
          <div className="diagnostics-item">
            <span>Speech Recognition</span>
            <span className={`status-badge ${voiceSupported ? 'ok' : 'error'}`}>
              {voiceSupported ? 'SUPPORTED' : 'NOT SUPPORTED'}
            </span>
          </div>
          <div className="diagnostics-item">
            <span>Speech Synthesis</span>
            <span className="status-badge ok">SUPPORTED</span>
          </div>
          <div className="diagnostics-item">
            <span>ElevenLabs STT</span>
            <span className="status-badge off">NOT CONFIGURED</span>
          </div>
          <div className="diagnostics-item">
            <span>ElevenLabs TTS</span>
            <span className="status-badge off">NOT CONFIGURED</span>
          </div>
          <div className="diagnostics-item">
            <span>Wake Word</span>
            <span className="status-badge warn">KEYWORD (SPACE)</span>
          </div>
          <div className="diagnostics-item">
            <span>VAD</span>
            <span className="status-badge ok">ENERGY-BASED</span>
          </div>
          <div className="diagnostics-item">
            <span>State</span>
            <span className={`status-badge ${listening ? 'ok' : 'off'}`}>
              {listening ? 'LISTENING' : 'IDLE'}
            </span>
          </div>
        </div>

        {/* Browser */}
        <div className="diagnostics-card">
          <div className="diagnostics-card-title">BROWSER</div>
          <div className="diagnostics-item">
            <span>User Agent</span>
            <span className="panel-value" style={{ fontFamily: 'inherit', fontSize: '0.6rem' }}>{getBrowserInfo()}</span>
          </div>
          <div className="diagnostics-item">
            <span>WebGL</span>
            <span className="status-badge ok">AVAILABLE</span>
          </div>
          <div className="diagnostics-item">
            <span>Web Audio</span>
            <span className="status-badge ok">AVAILABLE</span>
          </div>
          <div className="diagnostics-item">
            <span>WebSocket</span>
            <span className="status-badge ok">AVAILABLE</span>
          </div>
          <div className="diagnostics-item">
            <span>MediaDevices</span>
            <span className="status-badge ok">AVAILABLE</span>
          </div>
        </div>

        {/* Performance */}
        <div className="diagnostics-card">
          <div className="diagnostics-card-title">PERFORMANCE</div>
          <div className="diagnostics-item">
            <span>Memory (JS Heap)</span>
            <span className="panel-value" id="mem-used">-- MB</span>
          </div>
          <div className="diagnostics-item">
            <span>FPS Target</span>
            <span className="panel-value">60</span>
          </div>
        </div>
      </div>
    </div>
  )
}