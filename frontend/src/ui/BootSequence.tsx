
import { useState, useEffect, useCallback } from 'react'

interface BootSequenceProps {
  onComplete: (complete: boolean) => void
}

const BOOT_STEPS = [
  { id: 'core', label: 'INITIALIZING CORE SYSTEMS', duration: 800 },
  { id: 'memory', label: 'LOADING MEMORY MODULES', duration: 600 },
  { id: 'network', label: 'ESTABLISHING NEURAL LINK', duration: 1000 },
  { id: 'voice', label: 'CALIBRATING VOICE INTERFACE', duration: 700 },
  { id: 'bridge', label: 'CONNECTING TO BRIDGE', duration: 1200 },
  { id: 'ai', label: 'BOOTSTRAPPING AI CORE', duration: 1500 },
  { id: 'hud', label: 'RENDERING HUD INTERFACE', duration: 500 },
  { id: 'ready', label: 'SYSTEMS ONLINE', duration: 300 },
]

export function BootSequence({ onComplete }: BootSequenceProps) {
  const [currentStep, setCurrentStep] = useState(0)
  const [progress, setProgress] = useState(0)
  const [logs, setLogs] = useState<string[]>([])
  const [complete, setComplete] = useState(false)

  const addLog = useCallback((message: string, type: 'ok' | 'warn' | 'error' = 'ok') => {
    setLogs(prev => [...prev, `[${type.toUpperCase()}] ${message}`])
  }, [])

  useEffect(() => {
    const runBoot = async () => {
      for (let i = 0; i < BOOT_STEPS.length; i++) {
        const step = BOOT_STEPS[i]
        setCurrentStep(i)

        // Simulate progress within step
        const startProgress = (i / BOOT_STEPS.length) * 100
        const endProgress = ((i + 1) / BOOT_STEPS.length) * 100

        for (let p = startProgress; p <= endProgress; p += 2) {
          setProgress(p)
          await new Promise(r => setTimeout(r, step.duration / ((endProgress - startProgress) / 2)))
        }

        // Add log entry
        if (step.id === 'core') addLog('Core systems initialized')
        if (step.id === 'memory') addLog('Memory modules loaded: 8GB allocated')
        if (step.id === 'network') addLog('Neural link established: 127.0.0.1:8787')
        if (step.id === 'voice') addLog('Voice interface calibrated: Web Speech API')
        if (step.id === 'bridge') addLog('Bridge connection: OK')
        if (step.id === 'ai') addLog('AI core bootstrap: claude-opus-5')
        if (step.id === 'hud') addLog('HUD interface rendered: Three.js + React')
        if (step.id === 'ready') addLog('All systems nominal')
      }

      setComplete(true)
      onComplete(true)
    }

    runBoot()
  }, [addLog, onComplete])

  // Play boot sound (optional)
  useEffect(() => {
    // Could play audio here
  }, [])

  return (
    <div className="boot-sequence" role="status" aria-live="polite">
      <div className="boot-status">{BOOT_STEPS[currentStep]?.label || 'INITIALIZING...'}</div>

      <div className="boot-progress">
        <div
          className="boot-progress-bar"
          style={{ width: `${progress}%` }}
        ></div>
      </div>

      <div className="boot-log" role="log" aria-live="polite">
        {logs.map((log, i) => (
          <div key={i} className={`boot-log-entry ${log.includes('ERROR') ? 'error' : log.includes('WARN') ? 'warn' : 'ok'}`}>
            {log}
          </div>
        ))}
      </div>
    </div>
  )
}