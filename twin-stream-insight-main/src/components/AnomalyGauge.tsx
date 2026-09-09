import { useEffect, useRef } from 'react';

interface Props {
  score: number;
}

export function AnomalyGauge({ score }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const isAlarming = score > 5;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    const dpr = window.devicePixelRatio || 1;
    const size = 200;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    ctx.scale(dpr, dpr);

    const cx = size / 2, cy = size / 2, r = 75;
    const startAngle = 0.75 * Math.PI;
    const endAngle = 2.25 * Math.PI;
    const scoreAngle = startAngle + (score / 100) * (endAngle - startAngle);

    ctx.clearRect(0, 0, size, size);

    // bg arc
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.strokeStyle = 'hsl(213, 30%, 22%)';
    ctx.lineWidth = 12;
    ctx.lineCap = 'round';
    ctx.stroke();

    // value arc
    const color = score < 30 ? '#22c55e' : score < 60 ? '#f59e0b' : '#ef4444';
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, scoreAngle);
    ctx.strokeStyle = color;
    ctx.lineWidth = 12;
    ctx.lineCap = 'round';
    ctx.shadowColor = color;
    ctx.shadowBlur = 20;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // score text
    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 32px "JetBrains Mono"';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${Math.round(score)}%`, cx, cy - 6);

    ctx.fillStyle = 'hsl(200, 15%, 55%)';
    ctx.font = '12px Inter';
    ctx.fillText('ANOMALY SCORE', cx, cy + 24);

    // status label
    const status = score < 5 ? 'NOMINAL' : score < 30 ? 'ELEVATED' : score < 60 ? 'WARNING' : 'CRITICAL';
    ctx.fillStyle = color;
    ctx.font = 'bold 11px Inter';
    ctx.fillText(status, cx, cy + 42);
  }, [score]);

  return (
    <div className={`card-grid-glow rounded-lg p-5 flex flex-col items-center justify-center relative transition-all duration-300 ${isAlarming ? 'anomaly-flash-border' : ''}`}>
      <canvas ref={canvasRef} className="gauge-ring" />
    </div>
  );
}
