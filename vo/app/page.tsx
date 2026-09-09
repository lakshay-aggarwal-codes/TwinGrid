"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { PUEGauge } from "@/components/pue-gauge"
import { CoolingModeSelector } from "@/components/cooling-mode-selector"
import { Activity, Server, Thermometer } from "lucide-react"

function generatePUE(prev: number): number {
  const drift = (Math.random() - 0.48) * 0.06
  return Math.max(1.0, Math.min(2.0, parseFloat((prev + drift).toFixed(2))))
}

export default function Page() {
  const [pueValue, setPueValue] = useState(1.28)
  const [previousPue, setPreviousPue] = useState(1.32)
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date())
  const [mounted, setMounted] = useState(false)
  const mountedRef = useRef(false)

  const updatePUE = useCallback(() => {
    setPueValue((prev) => {
      setPreviousPue(prev)
      return generatePUE(prev)
    })
    setLastUpdate(new Date())
  }, [])

  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true
      setMounted(true)
    }
    const interval = setInterval(updatePUE, 4000)
    return () => clearInterval(interval)
  }, [updatePUE])

  return (
    <main className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border">
        <div className="mx-auto max-w-6xl flex items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-primary/10">
              <Server className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-wide text-foreground">
                DataCenter Monitor
              </h1>
              <p className="text-[11px] text-muted-foreground">
                Infrastructure Efficiency Dashboard
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
              </span>
              Live
            </div>
            <span className="text-[11px] font-mono text-muted-foreground">
              {mounted ? lastUpdate.toLocaleTimeString() : "\u00A0"}
            </span>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-6 py-8">
        {/* Stats bar */}
        <div className="grid grid-cols-3 gap-4 mb-8">
          {[
            {
              label: "Total IT Load",
              value: "2.4 MW",
              icon: <Activity className="h-4 w-4" />,
            },
            {
              label: "Facility Load",
              value: `${(pueValue * 2.4).toFixed(1)} MW`,
              icon: <Server className="h-4 w-4" />,
            },
            {
              label: "Ambient Temp",
              value: "24.6 C",
              icon: <Thermometer className="h-4 w-4" />,
            },
          ].map((stat) => (
            <div
              key={stat.label}
              className="flex items-center gap-3 rounded-xl border border-border bg-card p-4"
            >
              <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-secondary text-muted-foreground">
                {stat.icon}
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
                  {stat.label}
                </p>
                <p className="text-lg font-mono font-semibold text-foreground">
                  {stat.value}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Main content */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* PUE Gauge section */}
          <div className="rounded-xl border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-sm font-semibold text-foreground tracking-wide">
                  Power Usage Effectiveness
                </h2>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  Real-time efficiency ratio
                </p>
              </div>
              <span className="text-[10px] font-mono px-2 py-1 rounded-md bg-secondary text-muted-foreground">
                Auto-refresh 4s
              </span>
            </div>
            <div className="flex items-center justify-center">
              <PUEGauge value={pueValue} previousValue={previousPue} />
            </div>
          </div>

          {/* Cooling Mode section */}
          <div className="rounded-xl border border-border bg-card p-6">
            <div className="mb-6">
              <h2 className="text-sm font-semibold text-foreground tracking-wide">
                Cooling Mode
              </h2>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Select active cooling strategy
              </p>
            </div>
            <CoolingModeSelector />
          </div>
        </div>
      </div>
    </main>
  )
}
