import { useState, useRef, useCallback, useEffect } from 'react'

interface UseVoiceOptions {
  onTranscript: (text: string, isFinal: boolean) => void
  onError?: (error: Error) => void
}

export function useVoice({ onTranscript, onError }: UseVoiceOptions) {
  const [listening, setListening] = useState(false)
  const [supported, setSupported] = useState(false)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const _mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const _audioChunksRef = useRef<Blob[]>([])
  const _vadRef = useRef<AudioWorkletNode | null>(null)

  // Check browser support
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    setSupported(!!SpeechRecognition)
  }, [])

  // Initialize SpeechRecognition
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) return

    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognition.maxAlternatives = 1

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let finalTranscript = ''
      let interimTranscript = ''

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript
        if (event.results[i].isFinal) {
          finalTranscript += transcript
        } else {
          interimTranscript += transcript
        }
      }

      if (interimTranscript) {
        onTranscript(interimTranscript, false)
      }
      if (finalTranscript) {
        onTranscript(finalTranscript, true)
      }
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error('[Voice] Recognition error:', event.error)
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        onError?.(new Error(event.error))
      }
    }

    recognition.onend = () => {
      // Auto-restart if still listening
      if (listening && recognitionRef.current) {
        try {
          recognitionRef.current.start()
        } catch (e) {
          console.warn('[Voice] Restart failed:', e)
        }
      }
    }

    recognitionRef.current = recognition

    return () => {
      recognition.stop()
    }
  }, [listening, onTranscript, onError])

  // Voice Activity Detection using Web Audio API
  const setupVAD = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioContextRef.current = new AudioContext()
      const source = audioContextRef.current.createMediaStreamSource(stream)

      // Simple energy-based VAD
      const analyser = audioContextRef.current.createAnalyser()
      analyser.fftSize = 2048
      source.connect(analyser)

      const dataArray = new Uint8Array(analyser.frequencyBinCount)
      let silenceFrames = 0
      const SILENCE_THRESHOLD = 30
      const SILENCE_FRAMES_MAX = 30 // ~600ms at 50fps

      const checkVAD = () => {
        if (!audioContextRef.current || !listening) return

        analyser.getByteFrequencyData(dataArray)
        const sum = dataArray.reduce((a, b) => a + b, 0)
        const avg = sum / dataArray.length

        if (avg < SILENCE_THRESHOLD) {
          silenceFrames++
          if (silenceFrames > SILENCE_FRAMES_MAX) {
            // Stop listening after silence
            stopListening()
          }
        } else {
          silenceFrames = 0
        }

        requestAnimationFrame(checkVAD)
      }

      checkVAD()
    } catch (e) {
      console.warn('[Voice] VAD setup failed:', e)
    }
  }, [listening])

  const startListening = useCallback(() => {
    if (!supported) {
      onError?.(new Error('Speech recognition not supported'))
      return
    }

    if (recognitionRef.current && !listening) {
      try {
        recognitionRef.current.start()
        setListening(true)
        setupVAD()
      } catch (e) {
        console.error('[Voice] Start failed:', e)
        onError?.(e as Error)
      }
    }
  }, [supported, listening, setupVAD, onError])

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop()
    }
    setListening(false)
  }, [])

  // Text-to-Speech
  const speak = useCallback((text: string) => {
    if ('speechSynthesis' in window) {
      // Cancel any ongoing speech
      window.speechSynthesis.cancel()

      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'en-US'
      utterance.rate = 1
      utterance.pitch = 1
      utterance.volume = 1

      // Try to use a good voice
      const voices = window.speechSynthesis.getVoices()
      const preferred = voices.find(v =>
        v.name.includes('Google') || v.name.includes('Microsoft') || v.name.includes('Alex')
      )
      if (preferred) utterance.voice = preferred

      window.speechSynthesis.speak(utterance)
    }
  }, [])

  return {
    listening,
    startListening,
    stopListening,
    speak,
    supported,
  }
}

// Type declarations for SpeechRecognition
declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognition
    webkitSpeechRecognition: new () => SpeechRecognition
  }

  // eslint-disable-next-line @typescript-eslint/no-empty-object-type
  interface SpeechRecognition extends EventTarget {
    continuous: boolean
    interimResults: boolean
    lang: string
    maxAlternatives: number
    start(): void
    stop(): void
    abort(): void
    onresult: (event: SpeechRecognitionEvent) => void
    onerror: (event: SpeechRecognitionErrorEvent) => void
    onend: () => void
  }

  interface SpeechRecognitionEvent extends Event {
    resultIndex: number
    results: SpeechRecognitionResultList
  }

  interface SpeechRecognitionResultList {
    readonly length: number
    item(index: number): SpeechRecognitionResult
    [index: number]: SpeechRecognitionResult
  }

  interface SpeechRecognitionResult {
    readonly length: number
    readonly isFinal: boolean
    item(index: number): SpeechRecognitionAlternative
    [index: number]: SpeechRecognitionAlternative
  }

  interface SpeechRecognitionAlternative {
    readonly transcript: string
    readonly confidence: number
  }

  interface SpeechRecognitionErrorEvent extends Event {
    readonly error: string
    readonly message: string
  }
}