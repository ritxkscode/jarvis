import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useStore } from '../lib/store'

interface ReactorProps {
  intensity?: number
  color?: string
  style?: 'ring' | 'sphere' | 'wire'
  scale?: number
}

export function Reactor({ intensity = 0.5, color = '#00d4ff', style = 'ring', scale = 1 }: ReactorProps) {
  const groupRef = useRef<THREE.Group>(null!)
  const ringRef = useRef<THREE.Mesh>(null!)
  const sphereRef = useRef<THREE.Mesh>(null!)
  const particlesRef = useRef<THREE.Points>(null!)
  const timeRef = useRef(0)

  const { reactorColor, reactorIntensity, reactorStyle, reactorScale, reactorVisible } = useStore()

  // Use store values with props as fallback
  const currentColor = color || reactorColor
  const currentIntensity = intensity !== undefined ? intensity : reactorIntensity
  const currentStyle = style || reactorStyle
  const currentScale = scale !== undefined ? scale : reactorScale

  // Create geometry and materials
  const geometries = useMemo(() => {
    const ringGeo = new THREE.RingGeometry(0.8, 1, 64)
    ringGeo.rotateX(-Math.PI / 2)

    const sphereGeo = new THREE.SphereGeometry(1, 64, 64)

    const wireGeo = new THREE.IcosahedronGeometry(1, 3)
    const wireEdges = new THREE.EdgesGeometry(wireGeo)

    // Particles
    const particleGeo = new THREE.BufferGeometry()
    const particleCount = 2000
    const positions = new Float32Array(particleCount * 3)
    const sizes = new Float32Array(particleCount)
    const colors = new Float32Array(particleCount * 3)

    const colorObj = new THREE.Color(currentColor)

    for (let i = 0; i < particleCount; i++) {
      const radius = 0.5 + Math.random() * 2
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)

      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta)
      positions[i * 3 + 2] = radius * Math.cos(phi)

      sizes[i] = Math.random() * 2 + 0.5
      colors[i * 3] = colorObj.r
      colors[i * 3 + 1] = colorObj.g
      colors[i * 3 + 2] = colorObj.b
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    particleGeo.setAttribute('size', new THREE.BufferAttribute(sizes, 1))
    particleGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3))

    return { ringGeo, sphereGeo, wireEdges, particleGeo }
  }, [currentColor])

  const materials = useMemo(() => {
    const ringMat = new THREE.MeshBasicMaterial({
      color: currentColor,
      transparent: true,
      opacity: 0.3,
      side: THREE.DoubleSide,
      depthWrite: false,
    })

    const sphereMat = new THREE.MeshBasicMaterial({
      color: currentColor,
      transparent: true,
      opacity: 0.15,
      side: THREE.DoubleSide,
      depthWrite: false,
    })

    const wireMat = new THREE.LineBasicMaterial({
      color: currentColor,
      transparent: true,
      opacity: 0.5,
      linewidth: 2,
    })

    const particleMat = new THREE.PointsMaterial({
      size: 0.02,
      vertexColors: true,
      transparent: true,
      opacity: 0.6,
      sizeAttenuation: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })

    return { ringMat, sphereMat, wireMat, particleMat }
  }, [currentColor])

  // Animation
  useFrame((state, delta) => {
    if (!groupRef.current || !reactorVisible) return

    timeRef.current += delta

    const group = groupRef.current

    // Rotate based on style
    switch (currentStyle) {
      case 'ring':
        group.rotation.y += delta * 0.3 * currentIntensity
        group.rotation.x = Math.sin(timeRef.current * 0.5) * 0.1
        break
      case 'sphere':
        group.rotation.y += delta * 0.2 * currentIntensity
        group.rotation.x += delta * 0.1 * currentIntensity
        break
      case 'wire':
        group.rotation.y += delta * 0.4 * currentIntensity
        group.rotation.z += delta * 0.2 * currentIntensity
        break
    }

    // Pulse scale
    const pulseScale = 1 + Math.sin(timeRef.current * 2 * currentIntensity) * 0.05 * currentIntensity
    group.scale.setScalar(currentScale * pulseScale)

    // Animate ring
    if (ringRef.current) {
      ringRef.current.rotation.z += delta * 0.5 * currentIntensity
      const mat = ringRef.current.material as THREE.MeshBasicMaterial
      mat.opacity = 0.2 + 0.3 * currentIntensity
    }

    // Animate sphere
    if (sphereRef.current) {
      const mat = sphereRef.current.material as THREE.MeshBasicMaterial
      mat.opacity = 0.1 + 0.15 * currentIntensity
    }

    // Animate particles
    if (particlesRef.current) {
      particlesRef.current.rotation.y += delta * 0.1 * currentIntensity
      const positions = particlesRef.current.geometry.attributes.position.array as Float32Array
      for (let i = 0; i < positions.length; i += 3) {
        positions[i + 1] += Math.sin(timeRef.current * 2 + i) * 0.001 * currentIntensity
      }
      particlesRef.current.geometry.attributes.position.needsUpdate = true
    }

    // Update camera to look at reactor
    state.camera.lookAt(0, 0, 0)
  })

  if (!reactorVisible) return null

  return (
    <group ref={groupRef}>
      {/* Outer glow ring */}
      <mesh
        ref={ringRef}
        geometry={geometries.ringGeo}
        material={materials.ringMat}
        scale={currentStyle === 'ring' ? 1.5 : 0.5}
      />

      {/* Main reactor geometry */}
      {currentStyle === 'ring' && (
        <mesh
          geometry={geometries.ringGeo}
          material={materials.ringMat}
        />
      )}

      {currentStyle === 'sphere' && (
        <mesh
          ref={sphereRef}
          geometry={geometries.sphereGeo}
          material={materials.sphereMat}
        />
      )}

      {currentStyle === 'wire' && (
        <lineSegments
          geometry={geometries.wireEdges}
          material={materials.wireMat}
        />
      )}

      {/* Core glow */}
      <mesh
        geometry={geometries.ringGeo}
        material={new THREE.MeshBasicMaterial({
          color: currentColor,
          transparent: true,
          opacity: 0.5 * currentIntensity,
          side: THREE.DoubleSide,
          depthWrite: false,
        })}
        scale={0.3}
      />

      {/* Particle field */}
      <points
        ref={particlesRef}
        geometry={geometries.particleGeo}
        material={materials.particleMat}
      />

      {/* Central point light */}
      <pointLight
        color={currentColor}
        intensity={2 * currentIntensity}
        distance={10}
        decay={2}
      />
    </group>
  )
}