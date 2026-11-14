
import { useState } from 'react'

export function AudioTest({ onClose }: { onClose: () => void }) {
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<'success' | 'error' | null>(null)

  const runTest = async () => {
    setTesting(true)
    setResult(null)

    try {
      // Test speech synthesis
      if ('speechSynthesis' in window) {
        await new Promise<void>((resolve, reject) => {
          const utterance = new SpeechSynthesisUtterance('Audio test complete. Jarvis voice systems nominal.')
          utterance.lang = 'en-US'
          utterance.rate = 1
          utterance.onend = () => resolve()
          utterance.onerror = () => reject(new Error('TTS failed'))
          window.speechSynthesis.speak(utterance)
        })
      }

      // Test microphone access
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        stream.getTracks().forEach(t => t.stop())
      } catch {
        throw new Error('Microphone access denied')
      }

      setResult('success')
    } catch (e) {
      console.error('Audio test failed:', e)
      setResult('error')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="audio-test">
      <button
        className="audio-test-button"
        onClick={runTest}
        disabled={testing}
        aria-label="Run audio test"
      >
        {testing ? (
          <>
            <span className="spinner"></span>
            TESTING...
          </>
        ) : result === 'success' ? (
          '✓ AUDIO OK'
        ) : result === 'error' ? (
          '✗ AUDIO FAILED'
        ) : (
          'AUDIO TEST'
        )}
      </button>
    </div>
  )
}