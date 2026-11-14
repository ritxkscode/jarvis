import { useState, useEffect, useCallback, useRef } from 'react'

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
      case 'tool_result':
        // UI updates handled by store
        break
      case 'pong':
        // Heartbeat
        break
      case 'error':
        addTranscript('system', `Error: ${msg.message}`)
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