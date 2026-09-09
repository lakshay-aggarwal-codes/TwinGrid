import { useRef, useMemo, useState, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Text } from '@react-three/drei';
import * as THREE from 'three';

const COLS = 10;
const ROWS = 5;
const CELL_W = 0.9;
const CELL_H = 0.9;
const GAP = 0.1;

function tempToColor(t: number): THREE.Color {
  // t is 0-1, blue(cool) -> cyan -> green -> yellow -> red(hot)
  const c = new THREE.Color();
  if (t < 0.25) c.setHSL(0.6 - t * 0.8, 0.9, 0.45);
  else if (t < 0.5) c.setHSL(0.4 - (t - 0.25) * 1.2, 0.85, 0.45);
  else if (t < 0.75) c.setHSL(0.1 + (0.75 - t) * 0.4, 0.9, 0.5);
  else c.setHSL(0.0, 0.85, 0.35 + (t - 0.75) * 0.4);
  return c;
}

function HeatCell({ x, z, temp }: { x: number; z: number; temp: number }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const matRef = useRef<THREE.MeshStandardMaterial>(null);
  const targetColor = useMemo(() => tempToColor(temp), [temp]);
  const targetHeight = 0.1 + temp * 0.6;

  useFrame(() => {
    if (matRef.current) {
      matRef.current.color.lerp(targetColor, 0.08);
      matRef.current.emissive.lerp(targetColor, 0.05);
    }
    if (meshRef.current) {
      meshRef.current.scale.y += (targetHeight - meshRef.current.scale.y) * 0.08;
      meshRef.current.position.y = meshRef.current.scale.y / 2;
    }
  });

  return (
    <mesh ref={meshRef} position={[x * (CELL_W + GAP), targetHeight / 2, z * (CELL_H + GAP)]}>
      <boxGeometry args={[CELL_W, 1, CELL_H]} />
      <meshStandardMaterial
        ref={matRef}
        color={targetColor}
        emissive={targetColor}
        emissiveIntensity={0.3}
        roughness={0.4}
        metalness={0.3}
      />
    </mesh>
  );
}

function GridLabels() {
  const labels: JSX.Element[] = [];
  for (let c = 0; c < COLS; c++) {
    labels.push(
      <Text key={`col-${c}`} position={[c * (CELL_W + GAP), 0, -0.8]} fontSize={0.22} color="#64748b" anchorX="center">
        {`R${c + 1}`}
      </Text>
    );
  }
  for (let r = 0; r < ROWS; r++) {
    labels.push(
      <Text key={`row-${r}`} position={[-0.9, 0, r * (CELL_H + GAP)]} fontSize={0.22} color="#64748b" anchorX="center">
        {`A${r + 1}`}
      </Text>
    );
  }
  return <>{labels}</>;
}

function HeatGrid({ temperatures }: { temperatures: number[][] }) {
  return (
    <group position={[-(COLS - 1) * (CELL_W + GAP) / 2, 0, -(ROWS - 1) * (CELL_H + GAP) / 2]}>
      {temperatures.map((row, r) =>
        row.map((temp, c) => (
          <HeatCell key={`${r}-${c}`} x={c} z={r} temp={temp} />
        ))
      )}
      <GridLabels />
      {/* floor plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[(COLS - 1) * (CELL_W + GAP) / 2, -0.01, (ROWS - 1) * (CELL_H + GAP) / 2]}>
        <planeGeometry args={[COLS * (CELL_W + GAP) + 1, ROWS * (CELL_H + GAP) + 1]} />
        <meshStandardMaterial color="#0a1628" roughness={0.9} />
      </mesh>
    </group>
  );
}

function generateTemperatures(serverUtil: number, outsideTemp: number): number[][] {
  const grid: number[][] = [];
  for (let r = 0; r < ROWS; r++) {
    const row: number[] = [];
    for (let c = 0; c < COLS; c++) {
      const base = (serverUtil / 100) * 0.6;
      const hotAisle = r === 1 || r === 3 ? 0.2 : 0;
      const center = 1 - Math.abs(c - 4.5) / 5 * 0.3;
      const noise = (Math.random() - 0.5) * 0.1;
      const tempInfluence = (outsideTemp - 10) / 40 * 0.15;
      row.push(Math.max(0, Math.min(1, base + hotAisle + center * 0.1 + noise + tempInfluence)));
    }
    grid.push(row);
  }
  return grid;
}

interface Props {
  serverUtil: number;
  outsideTemp: number;
}

export function FloorHeatmap({ serverUtil, outsideTemp }: Props) {
  const [temps, setTemps] = useState(() => generateTemperatures(serverUtil, outsideTemp));

  useEffect(() => {
    setTemps(generateTemperatures(serverUtil, outsideTemp));
  }, [serverUtil, outsideTemp]);

  // animate changes periodically
  useEffect(() => {
    const interval = setInterval(() => {
      setTemps(generateTemperatures(serverUtil, outsideTemp));
    }, 4000);
    return () => clearInterval(interval);
  }, [serverUtil, outsideTemp]);

  return (
    <div className="card-grid-glow rounded-lg overflow-hidden">
      <div className="px-4 pt-4 pb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Data Centre Floor — Thermal Heatmap
        </h3>
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm" style={{ background: '#2563eb' }} />Cool</span>
          <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm" style={{ background: '#22c55e' }} />Normal</span>
          <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm" style={{ background: '#f59e0b' }} />Warm</span>
          <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm" style={{ background: '#ef4444' }} />Hot</span>
        </div>
      </div>
      <div className="h-[280px]">
        <Canvas camera={{ position: [0, 5, 6], fov: 45 }} gl={{ antialias: true }}>
          <ambientLight intensity={0.4} />
          <directionalLight position={[5, 8, 5]} intensity={0.6} />
          <pointLight position={[0, 3, 0]} intensity={0.4} color="#00E5FF" />
          <HeatGrid temperatures={temps} />
          <OrbitControls
            enablePan={false}
            enableZoom={true}
            maxPolarAngle={Math.PI / 2.2}
            minPolarAngle={0.3}
            minDistance={4}
            maxDistance={12}
          />
        </Canvas>
      </div>
    </div>
  );
}
