"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Droplets, RefreshCw, Wind, Shuffle, Star } from "lucide-react"

interface CoolingMode {
  id: string
  name: string
  icon: React.ReactNode
  color: string
  glowColor: string
  bgGradientFrom: string
  bgGradientTo: string
  waterUsage: number
  energyEfficiency: string
  bestConditions: string
}

const coolingModes: CoolingMode[] = [
  {
    id: "evaporative",
    name: "Evaporative",
    icon: <Droplets className="h-7 w-7" />,
    color: "#38bdf8",
    glowColor: "rgba(56, 189, 248, 0.4)",
    bgGradientFrom: "rgba(56, 189, 248, 0.12)",
    bgGradientTo: "rgba(56, 189, 248, 0.03)",
    waterUsage: 4,
    energyEfficiency: "92%",
    bestConditions: "Hot & dry climates",
  },
  {
    id: "closed-loop",
    name: "Closed Loop",
    icon: <RefreshCw className="h-7 w-7" />,
    color: "#22c55e",
    glowColor: "rgba(34, 197, 94, 0.4)",
    bgGradientFrom: "rgba(34, 197, 94, 0.12)",
    bgGradientTo: "rgba(34, 197, 94, 0.03)",
    waterUsage: 1,
    energyEfficiency: "78%",
    bestConditions: "Water-scarce regions",
  },
  {
    id: "free-air",
    name: "Free Air",
    icon: <Wind className="h-7 w-7" />,
    color: "#e2e8f0",
    glowColor: "rgba(226, 232, 240, 0.35)",
    bgGradientFrom: "rgba(226, 232, 240, 0.1)",
    bgGradientTo: "rgba(226, 232, 240, 0.02)",
    waterUsage: 0,
    energyEfficiency: "96%",
    bestConditions: "Cool ambient temps",
  },
  {
    id: "hybrid",
    name: "Hybrid",
    icon: <Shuffle className="h-7 w-7" />,
    color: "#a78bfa",
    glowColor: "rgba(167, 139, 250, 0.4)",
    bgGradientFrom: "rgba(167, 139, 250, 0.12)",
    bgGradientTo: "rgba(167, 139, 250, 0.03)",
    waterUsage: 2,
    energyEfficiency: "88%",
    bestConditions: "Variable climates",
  },
]

function WaterRating({ count, color }: { count: number; color: string }) {
  return (
    <div className="flex items-center gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          className="h-3 w-3"
          fill={i < count ? color : "transparent"}
          stroke={i < count ? color : "oklch(0.4 0 0)"}
          strokeWidth={1.5}
        />
      ))}
    </div>
  )
}

export function CoolingModeSelector() {
  const [selected, setSelected] = useState<string>("evaporative")

  return (
    <div className="w-full">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {coolingModes.map((mode) => {
          const isSelected = selected === mode.id
          return (
            <button
              key={mode.id}
              onClick={() => setSelected(mode.id)}
              className={cn(
                "group relative flex flex-col items-start gap-4 rounded-xl border p-5 text-left transition-all duration-300 cursor-pointer",
                "hover:scale-[1.02] active:scale-[0.98]",
                isSelected
                  ? "border-transparent"
                  : "border-border hover:border-muted-foreground/30"
              )}
              style={{
                background: isSelected
                  ? `linear-gradient(135deg, ${mode.bgGradientFrom}, ${mode.bgGradientTo})`
                  : undefined,
                boxShadow: isSelected
                  ? `0 0 20px ${mode.glowColor}, inset 0 0 0 1px ${mode.color}40`
                  : undefined,
              }}
              aria-pressed={isSelected}
            >
              {/* Animated glow ring on selected */}
              {isSelected && (
                <div
                  className="absolute inset-0 rounded-xl opacity-60 animate-pulse pointer-events-none"
                  style={{
                    boxShadow: `0 0 30px ${mode.glowColor}`,
                  }}
                />
              )}

              {/* Icon + Name row */}
              <div className="flex items-center gap-3">
                <div
                  className={cn(
                    "flex items-center justify-center h-11 w-11 rounded-lg transition-all duration-300",
                    isSelected ? "scale-110" : "scale-100"
                  )}
                  style={{
                    backgroundColor: isSelected
                      ? `${mode.color}20`
                      : "oklch(0.22 0.01 260)",
                    color: isSelected ? mode.color : "oklch(0.6 0 0)",
                    boxShadow: isSelected
                      ? `0 0 12px ${mode.color}30`
                      : undefined,
                  }}
                >
                  {mode.icon}
                </div>
                <div>
                  <h3
                    className={cn(
                      "font-semibold text-sm tracking-wide transition-colors duration-300"
                    )}
                    style={{
                      color: isSelected ? mode.color : "oklch(0.88 0 0)",
                    }}
                  >
                    {mode.name}
                  </h3>
                  <span className="text-[11px] text-muted-foreground">
                    {mode.bestConditions}
                  </span>
                </div>
              </div>

              {/* Stats */}
              <div className="flex flex-col gap-2.5 w-full">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
                    Water Usage
                  </span>
                  <WaterRating count={mode.waterUsage} color={mode.color} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
                    Energy Efficiency
                  </span>
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 rounded-full overflow-hidden bg-secondary">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: mode.energyEfficiency,
                          backgroundColor: isSelected
                            ? mode.color
                            : "oklch(0.5 0 0)",
                          boxShadow: isSelected
                            ? `0 0 6px ${mode.color}60`
                            : undefined,
                        }}
                      />
                    </div>
                    <span
                      className="text-xs font-mono font-medium"
                      style={{
                        color: isSelected ? mode.color : "oklch(0.6 0 0)",
                      }}
                    >
                      {mode.energyEfficiency}
                    </span>
                  </div>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
