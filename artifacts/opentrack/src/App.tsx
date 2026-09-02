import { type ChangeEvent, type CSSProperties, type MouseEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import {
  ChevronLeft,
  ChevronRight,
  Crosshair,
  LocateFixed,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  Undo2,
  Upload,
  Zap,
} from 'lucide-react';
import { Route, Switch, useLocation, Router as WouterRouter } from 'wouter';

type Point = { x: number; y: number; time: number };
type Mode = 'plot' | 'landing' | null;
type ShotData = {
  ballSpeed: string;
  carry: string;
  launchAngle: string;
  apex: string;
};

const queryClient = new QueryClient();
const DEFAULT_FPS = 60;

function formatTime(value: number) {
  if (!Number.isFinite(value) || value < 0) return '00:00.000';
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60);
  const millis = Math.floor((value % 1) * 1000);
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(millis).padStart(3, '0')}`;
}

function Home() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [fileName, setFileName] = useState('');
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [fps, setFps] = useState(String(DEFAULT_FPS));
  const [rotation, setRotation] = useState(0);
  const [points, setPoints] = useState<Point[]>([]);
  const [landingPoint, setLandingPoint] = useState<Point | null>(null);
  const [offScreenLanding, setOffScreenLanding] = useState(false);
  const [mode, setMode] = useState<Mode>(null);
  const [built, setBuilt] = useState(false);
  const [shotData, setShotData] = useState<ShotData>({
    ballSpeed: '',
    carry: '',
    launchAngle: '',
    apex: '',
  });

  const fpsNumber = Math.max(1, Number(fps) || DEFAULT_FPS);
  const totalFrames = duration > 0 ? Math.ceil(duration * fpsNumber) : 0;
  const currentFrame = duration > 0 ? Math.min(totalFrames, Math.floor(currentTime * fpsNumber) + 1) : 0;
  const progress = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;
  const canBuild = points.length >= 2;
  const fileStatus = videoUrl ? 'LOCAL SOURCE READY' : 'AWAITING SOURCE';

  const pathEnd = useMemo(
    () => offScreenLanding
      ? { x: 1.04, y: Math.max(0.12, (points[points.length - 1]?.y ?? 0.36) - 0.03) }
      : landingPoint ?? points[points.length - 1] ?? { x: 0.88, y: 0.33 },
    [landingPoint, offScreenLanding, points],
  );

  const selectFile = useCallback((file: File) => {
    if (!file.type.startsWith('video/')) return;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const nextUrl = URL.createObjectURL(file);
    objectUrlRef.current = nextUrl;
    setVideoUrl(nextUrl);
    setFileName(file.name);
    setDuration(0);
    setCurrentTime(0);
    setIsPlaying(false);
    setPoints([]);
    setLandingPoint(null);
    setOffScreenLanding(false);
    setMode(null);
    setBuilt(false);
  }, []);

  useEffect(() => () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  const redrawOverlay = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(rect.width * dpr));
    canvas.height = Math.max(1, Math.round(rect.height * dpr));
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    const toCanvas = (point: { x: number; y: number }) => ({ x: point.x * rect.width, y: point.y * rect.height });

    if (built && points.length >= 2) {
      const start = toCanvas(points[0]);
      const end = toCanvas(pathEnd);
      const control = {
        x: start.x + (end.x - start.x) * 0.53,
        y: Math.min(start.y, end.y) - rect.height * 0.36,
      };
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(start.x, start.y);
      for (let i = 1; i <= 45; i += 1) {
        const t = i / 45;
        const x = (1 - t) ** 2 * start.x + 2 * (1 - t) * t * control.x + t ** 2 * end.x;
        const y = (1 - t) ** 2 * start.y + 2 * (1 - t) * t * control.y + t ** 2 * end.y;
        ctx.lineTo(x, y);
      }
      ctx.setLineDash([7, 6]);
      ctx.lineWidth = 2;
      ctx.strokeStyle = 'rgba(255, 90, 0, .95)';
      ctx.shadowColor = 'rgba(255, 90, 0, .55)';
      ctx.shadowBlur = 9;
      ctx.stroke();
      ctx.restore();

      const startTime = points[0]?.time ?? 0;
      const endTime = landingPoint?.time ?? (offScreenLanding ? duration : points[points.length - 1]?.time) ?? duration;
      const flightWindow = endTime > startTime ? endTime - startTime : duration;
      const t = flightWindow > 0
        ? Math.min(1, Math.max(0, (currentTime - startTime) / flightWindow))
        : 0;
      const dot = {
        x: (1 - t) ** 2 * start.x + 2 * (1 - t) * t * control.x + t ** 2 * end.x,
        y: (1 - t) ** 2 * start.y + 2 * (1 - t) * t * control.y + t ** 2 * end.y,
      };
      ctx.save();
      ctx.beginPath();
      ctx.arc(dot.x, dot.y, 8, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(255, 90, 0, .32)';
      ctx.lineWidth = 2;
      ctx.shadowColor = '#ff5a00';
      ctx.shadowBlur = 18;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(dot.x, dot.y, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = '#ff5a00';
      ctx.fill();
      ctx.restore();
    }

    points.forEach((point, index) => {
      const target = toCanvas(point);
      ctx.save();
      ctx.beginPath();
      ctx.arc(target.x, target.y, 12, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(8, 10, 12, .88)';
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = '#ff5a00';
      ctx.stroke();
      ctx.fillStyle = '#ff7b39';
      ctx.font = '700 10px "Space Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(index + 1).padStart(2, '0'), target.x, target.y + .5);
      ctx.restore();
    });

    if (landingPoint) {
      const target = toCanvas(landingPoint);
      ctx.save();
      ctx.strokeStyle = '#d4d0c9';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.arc(target.x, target.y, 11, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(target.x - 5, target.y);
      ctx.lineTo(target.x + 5, target.y);
      ctx.moveTo(target.x, target.y - 5);
      ctx.lineTo(target.x, target.y + 5);
      ctx.stroke();
      ctx.restore();
    }
  }, [built, currentTime, duration, landingPoint, pathEnd, points]);

  useEffect(() => {
    redrawOverlay();
  }, [redrawOverlay, rotation, videoUrl]);

  useEffect(() => {
    const handleResize = () => redrawOverlay();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [redrawOverlay]);

  const handleCanvasClick = (event: MouseEvent<HTMLCanvasElement>) => {
    if (!mode) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const nextPoint = {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
      time: currentTime,
    };
    if (mode === 'plot') {
      setPoints((current) => [...current, nextPoint]);
      setBuilt(false);
    } else {
      setLandingPoint(nextPoint);
      setOffScreenLanding(false);
      setBuilt(false);
      setMode(null);
    }
  };

  const handleUndo = () => {
    if (landingPoint) {
      setLandingPoint(null);
      setBuilt(false);
      return;
    }
    setPoints((current) => current.slice(0, -1));
    setBuilt(false);
  };

  const togglePlayback = () => {
    const video = videoRef.current;
    if (!video || !videoUrl) return;
    if (video.paused) {
      void video.play();
      setIsPlaying(true);
    } else {
      video.pause();
      setIsPlaying(false);
    }
  };

  const stepVideo = (direction: -1 | 1) => {
    const video = videoRef.current;
    if (!video || !videoUrl) return;
    video.pause();
    setIsPlaying(false);
    video.currentTime = Math.max(0, Math.min(duration || Number.MAX_SAFE_INTEGER, video.currentTime + direction / fpsNumber));
    setCurrentTime(video.currentTime);
  };

  const handleSeek = (event: ChangeEvent<HTMLInputElement>) => {
    const next = Number(event.target.value);
    if (videoRef.current) videoRef.current.currentTime = next;
    setCurrentTime(next);
  };

  const handleMetadata = () => {
    const video = videoRef.current;
    if (!video) return;
    setDuration(Number.isFinite(video.duration) ? video.duration : 0);
    setCurrentTime(video.currentTime);
  };

  const startPlot = () => {
    setMode((current) => current === 'plot' ? null : 'plot');
  };

  const startLanding = () => {
    if (offScreenLanding) setOffScreenLanding(false);
    setMode((current) => current === 'landing' ? null : 'landing');
  };

  const setOffScreen = () => {
    setOffScreenLanding((current) => !current);
    setLandingPoint(null);
    setMode('landing');
    setBuilt(false);
  };

  const updateShotData = (field: keyof ShotData, value: string) => {
    setShotData((current) => ({ ...current, [field]: value }));
  };

  return (
    <div className="ot-app ot-noise">
      <nav className="ot-nav" aria-label="OpenTrack navigation">
        <div className="ot-brand" data-testid="text-wordmark">
          <span className="ot-mark" aria-hidden="true" />
          <span>OPENTRACK</span>
        </div>
        <div className="ot-nav-meta">
          <div className="ot-status" data-testid="status-source">
            <span className="ot-status-dot" />
            <span>{fileStatus}</span>
          </div>
          <label className="ot-fps">
            FPS
            <input
              data-testid="input-fps"
              type="number"
              min="1"
              max="1000"
              value={fps}
              onChange={(event) => setFps(event.target.value)}
              aria-label="Video frame rate"
            />
          </label>
        </div>
      </nav>

      <main className="ot-main">
        <header className="ot-heading">
          <div>
            <p className="ot-eyebrow">Local swing analysis / session 01</p>
            <h1 className="ot-title">Trace the flight.</h1>
          </div>
          <div className="ot-session" data-testid="text-session-source">
            {fileName || 'NO VIDEO LOADED'}
          </div>
        </header>

        <div className="ot-workspace">
          <section className="ot-stage-card" aria-label="Video editor stage">
            <div className="ot-stage-top">
              <span>Frame inspection</span>
              <div className="ot-stage-meta">
                <span data-testid="text-frame-readout">
                  F {currentFrame ? String(currentFrame).padStart(4, '0') : '----'} / {totalFrames ? String(totalFrames).padStart(4, '0') : '----'}
                </span>
                <span>{rotation === 0 ? 'ROT 000°' : `ROT ${String((rotation + 360) % 360).padStart(3, '0')}°`}</span>
              </div>
            </div>

            <div className="ot-stage-area instrument-grid">
              {videoUrl ? (
                <div className="ot-video-layer" style={{ transform: `rotate(${rotation}deg)` }}>
                  <video
                    ref={videoRef}
                    className="ot-video"
                    src={videoUrl}
                    onLoadedMetadata={handleMetadata}
                    onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
                    onPlay={() => setIsPlaying(true)}
                    onPause={() => setIsPlaying(false)}
                    onEnded={() => setIsPlaying(false)}
                    playsInline
                    data-testid="video-source"
                  />
                  <canvas
                    ref={canvasRef}
                    className="ot-canvas"
                    onClick={handleCanvasClick}
                    style={{ cursor: mode ? 'crosshair' : 'default' }}
                    data-testid="canvas-overlay"
                    aria-label="Shot plotting canvas"
                  />
                  {mode && (
                    <div className="ot-canvas-hint" data-testid="status-canvas-mode">
                      {mode === 'plot' ? 'CLICK TO DROP REFERENCE POINTS' : 'CLICK TO MARK LANDING'}
                    </div>
                  )}
                </div>
              ) : (
                <div className="ot-empty">
                  <div className="ot-empty-box">
                    <div className="ot-empty-cross" aria-hidden="true" />
                    <h2 className="ot-empty-title">Bring in a swing to begin</h2>
                    <p className="ot-empty-copy">
                      Load a video from this device. OpenTrack keeps the footage in this tab — nothing leaves your machine.
                    </p>
                    <button className="ot-button ot-button-primary" onClick={() => fileInputRef.current?.click()} data-testid="button-upload-empty">
                       <Upload size={14} /> Choose video
                    </button>
                  </div>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="video/*"
                hidden
                data-testid="input-video"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) selectFile(file);
                  event.target.value = '';
                }}
              />
            </div>

            <div className="ot-stage-footer">
              <button
                className="ot-button ot-play"
                onClick={togglePlayback}
                disabled={!videoUrl}
                aria-label={isPlaying ? 'Pause video' : 'Play video'}
                data-testid="button-play-pause"
              >
                {isPlaying ? <Pause size={15} /> : <Play size={15} />}
              </button>
              <input
                className="ot-scrub"
                type="range"
                min="0"
                max={duration || 0}
                step="0.001"
                value={Math.min(currentTime, duration || 0)}
                onChange={handleSeek}
                disabled={!videoUrl || !duration}
                style={{ '--progress': `${progress}%` } as CSSProperties}
                aria-label="Video timeline"
                data-testid="input-scrub"
              />
              <span className="ot-time" data-testid="text-time-readout">{formatTime(currentTime)}</span>
              <div className="ot-transport">
                <button className="ot-icon-button" onClick={() => stepVideo(-1)} disabled={!videoUrl} aria-label="Previous frame" data-testid="button-step-back">
                  <ChevronLeft size={16} />
                </button>
                <button className="ot-icon-button" onClick={() => stepVideo(1)} disabled={!videoUrl} aria-label="Next frame" data-testid="button-step-forward">
                  <ChevronRight size={16} />
                </button>
                <button className="ot-icon-button" onClick={() => setRotation((current) => (current + 270) % 360)} disabled={!videoUrl} aria-label="Rotate left" data-testid="button-rotate-left">
                  <RotateCcw size={15} />
                </button>
                <button className="ot-icon-button" onClick={() => setRotation((current) => (current + 90) % 360)} disabled={!videoUrl} aria-label="Rotate right" data-testid="button-rotate-right">
                  <RotateCw size={15} />
                </button>
              </div>
            </div>
          </section>

          <aside className="ot-panel" aria-label="Shot analysis controls">
            <section className="ot-panel-section">
              <div className="ot-panel-label">
                <span>Mark shot</span>
                {mode && <span className="ot-mode">{mode === 'plot' ? 'PLOT MODE' : 'LANDING MODE'}</span>}
              </div>
              <div className="ot-action-list">
                <button className={`ot-action ${mode === 'plot' ? 'is-active' : ''}`} onClick={startPlot} disabled={!videoUrl} data-testid="button-plot-launch">
                  <Crosshair size={16} />
                  <span className="ot-action-copy">
                    <span className="ot-action-title">Plot launch</span>
                    <span className="ot-action-hint">Drop reference points on stage</span>
                  </span>
                </button>
                <button className={`ot-action ${mode === 'landing' ? 'is-active' : ''}`} onClick={startLanding} disabled={!videoUrl} data-testid="button-mark-landing">
                  <LocateFixed size={16} />
                  <span className="ot-action-copy">
                    <span className="ot-action-title">Mark landing</span>
                    <span className="ot-action-hint">Set the visible impact point</span>
                  </span>
                </button>
              </div>
              <button className="ot-button ot-button-ghost ot-undo" onClick={handleUndo} disabled={!points.length && !landingPoint} data-testid="button-undo">
                <Undo2 size={13} /> Undo last mark
              </button>
              <div className="ot-check-row" style={{ marginTop: 14 }}>
                <span>Landing is off-screen</span>
                <button className={`ot-switch ${offScreenLanding ? 'is-on' : ''}`} onClick={setOffScreen} aria-label="Toggle landing off-screen" aria-pressed={offScreenLanding} data-testid="button-offscreen-toggle" />
              </div>
            </section>

            <section className="ot-panel-section">
              <div className="ot-panel-label">
                <span>Shot path</span>
                {built && <span className="ot-built-badge" data-testid="status-path-built">PATH BUILT</span>}
              </div>
              <button className="ot-button ot-button-primary ot-build" onClick={() => { setBuilt(true); setMode(null); }} disabled={!canBuild || built} data-testid="button-build-shot">
                <Zap size={14} /> {built ? 'Shot path built' : 'Build shot path'}
              </button>
              <p className="ot-build-note">
                {canBuild ? 'Fit a parabolic path through your marks.' : 'Plot at least two points to fit a path.'}
              </p>
            </section>

            <section className="ot-panel-section">
              <div className="ot-panel-label"><span>Shot data</span><span>OPTIONAL</span></div>
              <div className="ot-data-grid">
                <ShotField label="Ball speed" unit="mph" value={shotData.ballSpeed} onChange={(value) => updateShotData('ballSpeed', value)} testId="input-ball-speed" />
                <ShotField label="Carry" unit="yd" value={shotData.carry} onChange={(value) => updateShotData('carry', value)} testId="input-carry" />
                <ShotField label="Launch angle" unit="°" value={shotData.launchAngle} onChange={(value) => updateShotData('launchAngle', value)} testId="input-launch-angle" />
                <ShotField label="Height / apex" unit="ft" value={shotData.apex} onChange={(value) => updateShotData('apex', value)} testId="input-apex" />
              </div>
            </section>
          </aside>
        </div>

        <div className="ot-footer-note">
          <strong>LOCAL WORKSPACE</strong> — Video is read directly from your browser. Save your session by keeping this tab open.
        </div>
      </main>
    </div>
  );
}

function ShotField({
  label,
  unit,
  value,
  onChange,
  testId,
}: {
  label: string;
  unit: string;
  value: string;
  onChange: (value: string) => void;
  testId: string;
}) {
  return (
    <label className="ot-field">
      <span className="ot-field-label">{label}</span>
      <span className="ot-field-control">
        <input
          type="number"
          value={value}
          placeholder="—"
          onChange={(event) => onChange(event.target.value)}
          data-testid={testId}
          aria-label={label}
        />
        <span className="ot-field-unit">{unit}</span>
      </span>
    </label>
  );
}

function Router() {
  return (
    <RoutedErrorBoundary>
      <Switch>
        <Route path="/" component={Home} />
        <Route component={NotFound} />
      </Switch>
    </RoutedErrorBoundary>
  );
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
          <Router />
        </WouterRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;