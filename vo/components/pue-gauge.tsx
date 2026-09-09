"use client"

import { useEffect, useState, useRef } from "react"
import {
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
  ResponsiveContainer,
} from "recharts"
import { ArrowUp, ArrowDown, Minus } from "lucide-react"

interface PUEGaugeProps {
  value: number
  previousValue?: number
  size?: number
}

function getGaugeColor(value: number): string {
  if (value <= 1.2) return "#22c55e"
  if (value <= 1.35) return "#84cc16"
  if (value <= 1.5) return "#eab308"
  if (value <= 1.7) return "#f97316"
  return "#ef4444"
}

function getStatusLabel(value: number): string {
  if (value <= 1.2) return "Excellent"
  if (value <= 1.4) return "Good"
  if (value <= 1.5) return "Average"
  if (value <= 1.7) return "Below Avg"
  return "Poor"
}

function getGradientId(value: number): string {
  if (value <= 1.2) return "gaugeGreen"
  if (value <= 1.5) return "gaugeYellow"
  return "gaugeRed"
}

export function PUEGauge({
  value,
  previousValue,
  size = 280,
}: PUEGaugeProps) {
  const [animatedValue, setAnimatedValue] = useState(value)
  const [displayValue, setDisplayValue] = useState(value)
  const animationRef = useRef<number | null>(null)
  const startRef = useRef(value)

  useEffect(() => {
    const start = startRef.current
    const end = value
    const duration = 800
    const startTime = performance.now()

    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      const current = start + (end - start) * eased

      setAnimatedValue(current)
      setDisplayValue(parseFloat(current.toFixed(2)))

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate)
      } else {
        startRef.current = end
      }
    }

    animationRef.current = requestAnimationFrame(animate)
    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current)
    }
  }, [value])

  const normalizedValue = ((animatedValue - 1.0) / 1.0) * 100
  const clampedValue = Math.max(0, Math.min(100, normalizedValue))
  const color = getGaugeColor(animatedValue)
  const status = getStatusLabel(animatedValue)
  const gradientId = getGradientId(animatedValue)

  const delta = previousValue !== undefined ? value - previousValue : 0
  const deltaAbs = Math.abs(delta).toFixed(2)

  const data = [{ value: clampedValue, fill: `url(#${gradientId})` }]

  return (
    <div className="relative flex flex-col items-center">
      <div style={{ width: size, height: size }} className="relative">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%"
            cy="50%"
            innerRadius="78%"
            outerRadius="100%"
            barSize={14}
            data={data}
            startAngle={225}
            endAngle={-45}
          >
            <defs>
              <linearGradient id="gaugeGreen" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#22c55e" />
                <stop offset="100%" stopColor="#4ade80" />
              </linearGradient>
              <linearGradient id="gaugeYellow" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#84cc16" />
                <stop offset="100%" stopColor="#eab308" />
              </linearGradient>
              <linearGradient id="gaugeRed" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#f97316" />
                <stop offset="100%" stopColor="#ef4444" />
              </linearGradient>
              <filter id="glow">
                <feGaussianBlur stdDeviation="3" result="coloredBlur" />
                <feMerge>
                  <feMergeNode in="coloredBlur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <PolarAngleAxis
              type="number"
              domain={[0, 100]}
              angleAxisId={0}
              tick={false}
            />
            <RadialBar
              dataKey="value"
              cornerRadius={12}
              background={{ fill: "oklch(0.22 0.01 260)" }}
              isAnimationActive={false}
              style={{ filter: "url(#glow)" }}
            />
          </RadialBarChart>
        </ResponsiveContainer>

        {/* Center content */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="text-5xl font-mono font-bold tracking-tight transition-colors duration-500"
            style={{ color }}
          >
            {displayValue.toFixed(2)}
          </span>
          <span className="text-xs font-semibold tracking-widest uppercase text-muted-foreground mt-1">
            PUE
          </span>

          {/* Delta indicator */}
          {previousValue !== undefined && (
            <div
              className="flex items-center gap-1 mt-2 px-2 py-0.5 rounded-full text-xs font-medium"
              style={{
                backgroundColor:
                  delta > 0
                    ? "rgba(239, 68, 68, 0.15)"
                    : delta < 0
                    ? "rgba(34, 197, 94, 0.15)"
                    : "rgba(255, 255, 255, 0.08)",
                color:
                  delta > 0 ? "#ef4444" : delta < 0 ? "#22c55e" : "#a1a1aa",
              }}
            >
              {delta > 0 ? (
                <ArrowUp className="h-3 w-3" />
              ) : delta < 0 ? (
                <ArrowDown className="h-3 w-3" />
              ) : (
                <Minus className="h-3 w-3" />
              )}
              <span>{deltaAbs}</span>
            </div>
          )}
        </div>
      </div>

      {/* Status label */}
      <div className="flex items-center gap-2 mt-2">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }}
        />
        <span
          className="text-sm font-medium tracking-wide"
          style={{ color }}
        >
          {status}
        </span>
      </div>

      {/* Scale labels */}
      <div className="flex justify-between w-full max-w-[220px] mt-3 px-2">
        <span className="text-[10px] font-mono text-emerald-500/70">1.0</span>
        <span className="text-[10px] font-mono text-yellow-500/70">1.5</span>
        <span className="text-[10px] font-mono text-red-500/70">2.0</span>
      </div>
    </div>
  )
}
