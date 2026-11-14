import { create } from 'zustand'

interface UIState {
  // Reactor state
  reactorColor: string
  reactorIntensity: number
  reactorStyle: 'ring' | 'sphere' | 'wire'
  reactorScale: number
  reactorVisible: boolean

  // Orbit images
  orbitImages: string[]

  // Chrome/UI visibility
  showTranscript: boolean
  showSidePanels: boolean
  showRails: boolean
  showBadges: boolean

  // Theme
  accentColor: string
  backgroundColor: string

  // Connection status
  status: 'connected' | 'disconnected' | 'connecting'
  model: string

  // Actions
  setReactorColor: (color: string) => void
  setReactorIntensity: (intensity: number) => void
  setReactorStyle: (style: 'ring' | 'sphere' | 'wire') => void
  setReactorScale: (scale: number) => void
  setReactorVisible: (visible: boolean) => void
  addOrbitImage: (url: string) => void
  removeOrbitImage: (url: string) => void
  clearOrbitImages: () => void
  setShowTranscript: (show: boolean) => void
  setShowSidePanels: (show: boolean) => void
  setShowRails: (show: boolean) => void
  setShowBadges: (show: boolean) => void
  setAccentColor: (color: string) => void
  setBackgroundColor: (color: string) => void
  setStatus: (status: 'connected' | 'disconnected' | 'connecting') => void
  setModel: (model: string) => void
  reset: () => void
}

const initialState = {
  reactorColor: '#00d4ff',
  reactorIntensity: 0.5,
  reactorStyle: 'ring' as const,
  reactorScale: 1,
  reactorVisible: true,
  orbitImages: [],
  showTranscript: true,
  showSidePanels: true,
  showRails: true,
  showBadges: true,
  accentColor: '#00d4ff',
  backgroundColor: '#01060c',
  status: 'disconnected' as const,
  model: 'claude-opus-5',
}

export const useStore = create<UIState>((set) => ({
  ...initialState,

  setReactorColor: (color) => set({ reactorColor: color }),
  setReactorIntensity: (intensity) => set({ reactorIntensity: Math.max(0, Math.min(2, intensity)) }),
  setReactorStyle: (style) => set({ reactorStyle: style }),
  setReactorScale: (scale) => set({ reactorScale: Math.max(0.1, Math.min(3, scale)) }),
  setReactorVisible: (visible) => set({ reactorVisible: visible }),

  addOrbitImage: (url) => set((state) => ({
    orbitImages: [...state.orbitImages.slice(-9), url] // Max 10 images
  })),
  removeOrbitImage: (url) => set((state) => ({
    orbitImages: state.orbitImages.filter(u => u !== url)
  })),
  clearOrbitImages: () => set({ orbitImages: [] }),

  setShowTranscript: (show) => set({ showTranscript: show }),
  setShowSidePanels: (show) => set({ showSidePanels: show }),
  setShowRails: (show) => set({ showRails: show }),
  setShowBadges: (show) => set({ showBadges: show }),

  setAccentColor: (color) => set({ accentColor: color }),
  setBackgroundColor: (color) => set({ backgroundColor: color }),

  setStatus: (status) => set({ status }),
  setModel: (model) => set({ model }),

  reset: () => set(initialState),
}))