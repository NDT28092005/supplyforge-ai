import { CommonModule, isPlatformBrowser } from '@angular/common';
import {
  AfterViewInit,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  Inject,
  Input,
  OnDestroy,
  Output,
  PLATFORM_ID,
  ViewChild
} from '@angular/core';
import { Router } from '@angular/router';
import { gsap } from 'gsap';
import { ScrollToPlugin } from 'gsap/ScrollToPlugin';

import { ApiService } from '../api.service';
import { IngestionStateService } from '../core/state/ingestion-state.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

interface JourneyScene {
  eyebrow: string;
  title: string;
  body: string;
  metricLabel: string;
  metric: string;
}

@Component({
  selector: 'app-trust-theater-hero',
  standalone: true,
  imports: [CommonModule, PageMotionDirective],
  templateUrl: './trust-theater-hero.component.html',
  styleUrls: ['./trust-theater-hero.component.css']
})
export class TrustTheaterHeroComponent implements AfterViewInit, OnDestroy {
  @ViewChild('pageRoot') pageRoot?: ElementRef<HTMLElement>;
  @ViewChild('journeyRoot') journeyRoot?: ElementRef<HTMLElement>;

  @Output() upload = new EventEmitter<{ file: File }>();
  @Output() openLogin = new EventEmitter<void>();
  @Output() navigateStage = new EventEmitter<string>();
  @Input() user: any = null;

  readonly journeyScenes: JourneyScene[] = [
    {
      eyebrow: 'Chặng 01 / Dữ liệu',
      title: 'Nạp một file, không thêm một dự án IT.',
      body: 'Bắt đầu bằng CSV từ sàn hoặc phần mềm bạn đang dùng. Hệ thống kiểm tra cấu trúc, ngày bán và bản ghi trùng trước khi phân tích.',
      metricLabel: 'Đầu vào',
      metric: 'File CSV quen thuộc'
    },
    {
      eyebrow: 'Chặng 02 / Tín hiệu',
      title: 'Đặt hàng chậm vào đúng bối cảnh.',
      body: 'SupplyForge đọc sức bán, tồn và giá trị vốn theo nhiều cửa sổ thời gian để phân biệt một tuần chậm với một xu hướng thật.',
      metricLabel: 'Góc nhìn',
      metric: '7 / 30 / 90 ngày'
    },
    {
      eyebrow: 'Chặng 03 / Hành động',
      title: 'Biết việc nào nên làm trước.',
      body: 'Thay vì một điểm rủi ro khó hiểu, bạn nhận được danh sách ưu tiên, lý do phía sau và hướng xử lý để đội ngũ cùng duyệt.',
      metricLabel: 'Đầu ra',
      metric: 'SKU → vốn → bước tiếp theo'
    }
  ];

  localFile: File | null = null;
  showDuplicateFileModal = false;
  isUploading = false;
  activeWorldScene = 0;

  private disposeMotion?: () => void;
  private scrollListener?: () => void;
  private resizeListener?: () => void;
  private scrollFrame = 0;

  constructor(
    private apiService: ApiService,
    private ingestionState: IngestionStateService,
    private router: Router,
    private changeDetector: ChangeDetectorRef,
    @Inject(PLATFORM_ID) private platformId: object
  ) {}

  ngAfterViewInit(): void {
    if (!isPlatformBrowser(this.platformId) || !this.pageRoot || !this.journeyRoot) return;

    gsap.registerPlugin(ScrollToPlugin);
    const root = this.pageRoot.nativeElement;
    const journey = this.journeyRoot.nativeElement;
    let media: gsap.MatchMedia | undefined;

    const context = gsap.context(() => {
      media = gsap.matchMedia();
      media.add(
        {
          desktop: '(min-width: 820px)',
          reduceMotion: '(prefers-reduced-motion: reduce)'
        },
        (condition) => {
          const { desktop, reduceMotion } = condition.conditions as { desktop: boolean; reduceMotion: boolean };
          if (reduceMotion) return undefined;

          const timeline = gsap.timeline({ defaults: { ease: 'power3.out' } });
          timeline
            .fromTo('[data-motion="header"] .hero-overline', { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.35 })
            .fromTo('[data-motion="header"] h1', { autoAlpha: 0, y: 18 }, { autoAlpha: 1, y: 0, duration: 0.55 }, '-=0.16')
            .fromTo('[data-motion="header"] .hero-summary', { autoAlpha: 0, y: 12 }, { autoAlpha: 1, y: 0, duration: 0.42 }, '-=0.24')
            .fromTo('[data-motion="header"] .hero-actions', { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.35 }, '-=0.18')
            .fromTo('[data-motion="header"] .hero-visual', { autoAlpha: 0, x: desktop ? 24 : 0 }, { autoAlpha: 1, x: 0, duration: 0.65 }, '-=0.5')
            .fromTo('[data-hero-illustration]', { autoAlpha: 0, y: 22, scale: 1.03 }, { autoAlpha: 0.76, y: 0, scale: 1, duration: 0.7 }, '-=0.52')
            .fromTo('[data-import-window]', { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.42 }, '-=0.34')
            .fromTo('.signal-strip', { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.35 }, '-=0.25');

          return () => timeline.kill();
        },
        root
      );
    }, root);

    this.disposeMotion = () => {
      media?.revert();
      context.revert();
    };

    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      this.setupWorldScroll(journey);
    }
  }

  ngOnDestroy(): void {
    this.disposeMotion?.();
    if (this.scrollListener) window.removeEventListener('scroll', this.scrollListener);
    if (this.resizeListener) window.removeEventListener('resize', this.resizeListener);
    if (this.scrollFrame) cancelAnimationFrame(this.scrollFrame);
  }

  scrollToJourney(): void {
    const target = this.journeyRoot?.nativeElement;
    if (!target || !isPlatformBrowser(this.platformId)) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      target.scrollIntoView();
      return;
    }
    gsap.registerPlugin(ScrollToPlugin);
    gsap.to(window, { duration: 0.75, scrollTo: { y: target, offsetY: 76 }, ease: 'power3.inOut' });
  }

  scrollToTopAndUpload(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.scrollTo({ top: 0 });
      return;
    }
    gsap.registerPlugin(ScrollToPlugin);
    gsap.to(window, { duration: 0.75, scrollTo: { y: 0 }, ease: 'power3.inOut' });
  }

  onContactSupport(): void {
    this.navigateStage.emit('services');
    this.router.navigate(['/services']);
  }

  fileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) this.localFile = input.files[0];
  }

  removeFile(): void {
    this.localFile = null;
  }

  returnToDashboardFromDuplicate(): void {
    this.showDuplicateFileModal = false;
    this.localFile = null;
    this.ingestionState.reset();
    this.ingestionState.setSessionType('INITIAL');
    this.router.navigate(['/app/dashboard']);
  }

  chooseAnotherFile(): void {
    this.showDuplicateFileModal = false;
    this.localFile = null;
  }

  onUpload(): void {
    if (!this.localFile) return;

    this.upload.emit({ file: this.localFile });
    this.isUploading = true;
    this.ingestionState.setSessionType('INITIAL');
    this.ingestionState.setFile(this.localFile);
    this.ingestionState.setErrorMessage('');

    this.apiService.uploadCsvV2(this.localFile, 1, 'INITIAL').subscribe({
      next: (res: any) => {
        this.isUploading = false;

        if (res?.idempotent_retry) {
          this.showDuplicateFileModal = true;
          return;
        }

        if (res?.sessionId) this.ingestionState.setSessionId(res.sessionId);

        if (res?.status === 'REJECT' || res?.profile?.validation?.status === 'REJECT') {
          const errorMsg = res?.error || res?.profile?.validation?.errors?.join('; ') || 'File CSV không hợp lệ hoặc bị hệ thống từ chối.';
          this.ingestionState.setErrorMessage(errorMsg);
          this.router.navigate(['/app/import']);
          return;
        }

        const profile = res?.profile;
        if (profile) {
          const mappingData = {
            headers: profile.headers,
            sampleData: profile.previewRows ? profile.previewRows[0] : null,
            aiSuggestions: {
              sku_column_index: profile.headers.indexOf(profile.skuColumnDetected),
              record_date_column_index: profile.headers.indexOf(profile.dateColumnDetected),
              confidence: 'High (Streaming CSV Profiler)'
            }
          };
          this.ingestionState.setMappingData(mappingData);
          this.router.navigate(['/app/import/processing']);
        } else {
          this.ingestionState.setErrorMessage('Không nhận diện được cấu trúc file CSV.');
          this.router.navigate(['/app/import']);
        }
      },
      error: (err: any) => {
        this.isUploading = false;
        const errorMsg = err.error?.error || 'File CSV không hợp lệ (sai mã hóa, trùng cột, thiếu header hoặc rỗng).';
        this.ingestionState.setErrorMessage(errorMsg);
        this.router.navigate(['/app/import']);
      }
    });
  }

  getFileSizeKb(file: File | null): string {
    if (!file) return '0.0';
    return (file.size / 1024).toFixed(1);
  }

  private setupWorldScroll(journey: HTMLElement): void {
    const progress = journey.querySelector<SVGPathElement>('[data-world-progress]');
    const nodes = Array.from(journey.querySelectorAll<SVGCircleElement>('[data-world-node]'));
    const steps = Array.from(journey.querySelectorAll<HTMLElement>('[data-world-step]'));
    if (!progress || !nodes.length || !steps.length) return;

    const progressTo = gsap.quickTo(progress, 'strokeDashoffset', { duration: 0.28, ease: 'power2.out' });
    const nodeScaleTo = nodes.map((node) => gsap.quickTo(node, 'scale', { duration: 0.25, ease: 'power2.out' }));
    const stepOpacityTo = steps.map((step) => gsap.quickTo(step, 'autoAlpha', { duration: 0.24, ease: 'power2.out' }));
    const stepYTo = steps.map((step) => gsap.quickTo(step, 'y', { duration: 0.24, ease: 'power2.out' }));
    const sceneIllustration = journey.querySelector<HTMLElement>('.scene-illustration');
    const sceneIllustrationYTo = sceneIllustration
      ? gsap.quickTo(sceneIllustration, 'yPercent', { duration: 0.35, ease: 'power2.out' })
      : undefined;
    const normalizeProgress = gsap.utils.clamp(0, 1);
    const mapScene = gsap.utils.mapRange(0, 1, 0, steps.length - 1);
    const routeLength = progress.getTotalLength();

    progress.style.strokeDasharray = `${routeLength}`;
    progress.style.strokeDashoffset = `${routeLength}`;
    gsap.set(steps, { autoAlpha: 0.4, y: 10 });
    gsap.set(nodes, { transformOrigin: 'center center', scale: 0.76 });

    const update = () => {
      const scrollableDistance = Math.max(1, journey.offsetHeight - window.innerHeight);
      const rawProgress = -journey.getBoundingClientRect().top / scrollableDistance;
      const progressValue = normalizeProgress(rawProgress);
      const sceneValue = mapScene(progressValue);
      const activeScene = Math.min(steps.length - 1, Math.floor(sceneValue + 0.45));

      progressTo(routeLength * (1 - progressValue));
      sceneIllustrationYTo?.(gsap.utils.mapRange(0, 1, 2, -8, progressValue));
      nodes.forEach((_, index) => nodeScaleTo[index](index === activeScene ? 1.12 : 0.76));
      steps.forEach((_, index) => {
        const distance = Math.abs(index - sceneValue);
        stepOpacityTo[index](distance < 0.8 ? 1 : 0.36);
        stepYTo[index](distance < 0.8 ? 0 : 10);
      });

      if (activeScene !== this.activeWorldScene) {
        this.activeWorldScene = activeScene;
        this.changeDetector.markForCheck();
      }
    };

    this.scrollListener = () => {
      if (this.scrollFrame) return;
      this.scrollFrame = requestAnimationFrame(() => {
        this.scrollFrame = 0;
        update();
      });
    };
    this.resizeListener = this.scrollListener;
    window.addEventListener('scroll', this.scrollListener, { passive: true });
    window.addEventListener('resize', this.resizeListener, { passive: true });
    update();
  }
}
