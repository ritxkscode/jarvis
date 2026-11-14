import { useState, useEffect, useCallback, useRef } from 'react'
import { useStore } from '../lib/store'

interface TranscriptEntry {
  id: string
  role: 'user' | 'jarvis' | 'system'
  text: string
  timestamp: Date
}

interface BridgeMessage {
  type: string
  [key: string]: any
}

export function useBridge() {
  const [connected, setConnected] = useState(false)
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clientIdRef = useRef<string>('')

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket('ws://localhost:8787/ws')
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[Bridge] Connected')
      setConnected(true)
    }

    ws.onmessage = (event) => {
      try {
        const msg: BridgeMessage = JSON.parse(event.data)
        handleMessage(msg)
      } catch (e) {
        console.error('[Bridge] Parse error:', e)
      }
    }

    ws.onclose = () => {
      console.log('[Bridge] Disconnected')
      setConnected(false)
      // Reconnect after 3 seconds
      reconnectTimeoutRef.current = setTimeout(connect, 3000)
    }

    ws.onerror = (err) => {
      console.error('[Bridge] Error:', err)
    }
  }, [])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    wsRef.current?.close()
    wsRef.current = null
    setConnected(false)
  }, [])

  const handleMessage = useCallback((msg: BridgeMessage) => {
    switch (msg.type) {
      case 'welcome':
        clientIdRef.current = msg.client_id
        break
      case 'voice':
        if (msg.action === 'response' && msg.response) {
          addTranscript('jarvis', msg.response)
        }
        if (msg.transcript) {
          addTranscript('user', msg.transcript)
        }
        break
      case 'chat_response':
        if (msg.text) {
          addTranscript('jarvis', msg.text)
        }
        break
      case 'tool_call':
        // Execute UI control tool on the store
        handleToolCall(msg)
        break
      case 'tool_result':
        // Confirmation received
        break
      case 'pong':
        // Heartbeat
        break
      case 'error':
        addTranscript('system', `Error: ${msg.message}`)
        break
    }
  }, [])

  const handleToolCall = useCallback((msg: BridgeMessage) => {
    const { tool, args } = msg
    const store = useStore.getState()

    switch (tool) {
      case 'ui_theme':
        if (args.accentColor) store.setAccentColor(args.accentColor)
        if (args.backgroundColor) store.setBackgroundColor(args.backgroundColor)
        break
      case 'ui_reactor':
        if (args.color) store.setReactorColor(args.color)
        if (args.intensity !== undefined) store.setReactorIntensity(args.intensity)
        if (args.style) store.setReactorStyle(args.style)
        if (args.scale !== undefined) store.setReactorScale(args.scale)
        if (args.visible !== undefined) store.setReactorVisible(args.visible)
        break
      case 'ui_orbit':
        if (args.action === 'add' && args.url) store.addOrbitImage(args.url)
        else if (args.action === 'remove' && args.url) store.removeOrbitImage(args.url)
        else if (args.action === 'clear') store.clearOrbitImages()
        break
      case 'ui_chrome':
        if (args.transcript !== undefined) store.setShowTranscript(args.transcript)
        if (args.sidePanels !== undefined) store.setShowSidePanels(args.sidePanels)
        if (args.rails !== undefined) store.setShowRails(args.rails)
        if (args.badges !== undefined) store.setShowBadges(args.badges)
        break
      case 'ui_effect':
        // Trigger visual effects (pulse, flash, etc.)
        if (args.type === 'pulse' && args.color) {
          const originalColor = store.reactorColor
          store.setReactorColor(args.color)
          setTimeout(() => store.setReactorColor(originalColor), args.duration || 500)
        }
        break
      case 'ui_screen':
        if (args.action === 'clear') {
          // Clear transcript
          useStore.getState().clearOrbitImages()
        }
        break
      case 'ui_reset':
        store.reset()
        break
    }
  }, [])

  const addTranscript = useCallback((role: TranscriptEntry['role'], text: string) => {
    const entry: TranscriptEntry = {
      id: crypto.randomUUID(),
      role,
      text,
      timestamp: new Date(),
    }
    setTranscripts(prev => [...prev.slice(-49), entry]) // Keep last 50
  }, [])

  const sendMessage = useCallback((msg: BridgeMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  const clearTranscripts = useCallback(() => {
    setTranscripts([])
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [disconnect])

  return {
    connected,
    connect,
    disconnect,
    sendMessage,
    transcripts,
    clearTranscripts,
  }
}