
import { useStore } from '../lib/store'

interface SidePanelsProps {
  connected: boolean
  listening: boolean
}

export function SidePanels({ connected, listening }: SidePanelsProps) {
  const { showSidePanels, reactorColor, reactorStyle, reactorIntensity, status, model } = useStore()

  if (!showSidePanels) return null

  const formatTime = () => new Date().toLocaleTimeString('en-US', { hour12: false })

  return (
    <>
      {/* Left Panel - System Status */}
      <div className="hud-left">
        <div className="hud-panel">
          <div className="panel-title">SYSTEM STATUS</div>
          <div className="panel-content">
            <div className="panel-row">
              <span className="panel-label">BRIDGE</span>
              <span className="panel-value">{connected ? 'ONLINE' : 'OFFLINE'}</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">VOICE</span>
              <span className="panel-value">{listening ? 'ACTIVE' : 'STANDBY'}</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">MODEL</span>
              <span className="panel-value">{model}</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">STATUS</span>
              <span className="panel-value">{status.toUpperCase()}</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">UPTIME</span>
              <span className="panel-value" id="uptime">00:00:00</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">LOCAL TIME</span>
              <span className="panel-value" id="localtime">{formatTime()}</span>
            </div>
          </div>
        </div>

        <div className="hud-panel">
          <div className="panel-title">REACTOR CONFIG</div>
          <div className="panel-content">
            <div className="panel-row">
              <span className="panel-label">STYLE</span>
              <span className="panel-value">{reactorStyle.toUpperCase()}</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">INTENSITY</span>
              <span className="panel-value">{(reactorIntensity * 100).toFixed(0)}%</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">COLOR</span>
              <span className="panel-value" style={{ color: reactorColor }}>{reactorColor}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Right Panel - Capabilities */}
      <div className="hud-right">
        <div className="hud-panel">
          <div className="panel-title">CAPABILITIES</div>
          <div className="panel-content">
            <div className="panel-row">
              <span className="panel-label">WEB SEARCH</span>
              <span className="panel-value">EXA / SERPER</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">IMAGE GEN</span>
              <span className="panel-value">HIGGSFIELD</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">BROWSER</span>
              <span className="panel-value">PLAYWRIGHT</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">PHONE</span>
              <span className="panel-value">ANDROID MCP</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">VOICE</span>
              <span className="panel-value">ELEVENLABS</span>
            </div>
            <div className="panel-row">
              <span className="panel-label">FILES</span>
              <span className="panel-value">LOCAL MCP</span>
            </div>
          </div>
        </div>

        <div className="hud-panel">
          <div className="panel-title">QUICK ACTIONS</div>
          <div className="panel-content" style={{ fontSize: '0.75rem', lineHeight: '2' }}>
            <div style={{ color: 'var(--accent)', marginBottom: '0.5rem' }}>VOICE COMMANDS:</div>
            <div>• "Hey Jarvis" - Wake</div>
            <div>• "Search for..." - Web search</div>
            <div>• "Generate image of..." - AI art</div>
            <div>• "Open GitHub" - Browser</div>
            <div>• "Screenshot phone" - Android</div>
            <div>• "Read my emails" - Gmail</div>
            <div>• "Create reminder" - Tasks</div>
          </div>
        </div>
      </div>
    </>
  )
}