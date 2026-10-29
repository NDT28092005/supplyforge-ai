import { CommonModule, isPlatformBrowser } from '@angular/common';
import {
  AfterViewInit,
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
import { ScrollTrigger } from 'gsap/ScrollTrigger';

import { ApiService } from '../api.service';
import { IngestionStateService } from '../core/state/ingestion-state.service';
import { DashboardStateService } from '../core/state/dashboard-state.service';
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
      eyebrow: 'Giai đoạn 01 / Dữ liệu đầu vào',
      title: 'Chuẩn hóa dữ liệu bán hàng từ nguồn hiện có.',
      body: 'Bắt đầu từ tệp CSV của sàn bán hàng hoặc hệ thống đang sử dụng. Hệ thống kiểm tra cấu trúc, thời điểm bán và bản ghi trùng trước khi phân tích.',
      metricLabel: 'Nguồn dữ liệu',
      metric: 'Tệp CSV vận hành'
    },
    {
      eyebrow: 'Giai đoạn 02 / Phân tích thời gian',
      title: 'Đánh giá tín hiệu bán hàng trong đúng bối cảnh.',
      body: 'SupplyForge phân tích tốc độ bán, giá trị vốn và mức độ gián đoạn theo nhiều cửa sổ thời gian để phân biệt biến động ngắn hạn với xu hướng cần theo dõi.',
      metricLabel: 'Cửa sổ quan sát',
      metric: '7 / 30 / 90 ngày'
    },
    {
      eyebrow: 'Giai đoạn 03 / Hỗ trợ quyết định',
      title: 'Ưu tiên danh mục cần được xem xét.',
      body: 'Thay vì một điểm rủi ro đơn lẻ, đội ngũ nhận được danh sách ưu tiên, các tín hiệu liên quan và phương án để xem xét, phê duyệt và triển khai.',
      metricLabel: 'Đầu ra phân tích',
      metric: 'SKU → vốn → phương án'
    }
  ];

  localFile: File | null = null;
  showDuplicateFileModal = false;
  isUploading = false;
  private disposeMotion?: () => void;

  constructor(
    private apiService: ApiService,
    private ingestionState: IngestionStateService,
    private dashboardState: DashboardStateService,
    private router: Router,
    @Inject(PLATFORM_ID) private platformId: object
  ) {}

  ngAfterViewInit(): void {
    if (!isPlatformBrowser(this.platformId) || !this.pageRoot || !this.journeyRoot) return;

    gsap.registerPlugin(ScrollToPlugin, ScrollTrigger);
    const root = this.pageRoot.nativeElement;
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
            .fromTo('[data-import-window]', { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.42 }, '-=0.34')
            .fromTo('.signal-strip', { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.35 }, '-=0.25');

          if (desktop) this.setupJourneyScroll(root);

          return () => timeline.kill();
        },
        root
      );
    }, root);

    this.disposeMotion = () => {
      media?.revert();
      context.revert();
    };

  }

  ngOnDestroy(): void {
    this.disposeMotion?.();
  }

  private setupJourneyScroll(root: HTMLElement): void {
    const journey = this.journeyRoot?.nativeElement;
    const route = root.querySelector<SVGPathElement>('[data-journey-route]');
    const steps = Array.from(root.querySelectorAll<HTMLElement>('[data-journey-step]'));
    const nodes = Array.from(root.querySelectorAll<SVGCircleElement>('[data-journey-node]'));
    const stageLabel = root.querySelector<HTMLElement>('[data-journey-stage]');

    if (!journey || !route || steps.length === 0 || nodes.length === 0) return;

    const routeLength = route.getTotalLength();
    gsap.set(route, { strokeDasharray: routeLength, strokeDashoffset: routeLength });
    gsap.set(nodes, { autoAlpha: 0.48, scale: 0.72, transformOrigin: '50% 50%' });

    const setStage = (stageIndex: number): void => {
      const completeRatio = (stageIndex + 1) / steps.length;

      gsap.to(route, {
        strokeDashoffset: routeLength * (1 - completeRatio),
        duration: 0.32,
        ease: 'power2.out',
        overwrite: 'auto'
      });
      gsap.to(nodes, {
        autoAlpha: (index: number) => index <= stageIndex ? 1 : 0.48,
        scale: (index: number) => index <= stageIndex ? 1 : 0.72,
        duration: 0.28,
        ease: 'power2.out',
        overwrite: 'auto'
      });

      steps.forEach((step, index) => step.classList.toggle('is-current', index === stageIndex));
      if (stageLabel) stageLabel.textContent = `0${stageIndex + 1} / 0${steps.length}`;
    };

    steps.forEach((step, index) => {
      ScrollTrigger.create({
        trigger: step,
        start: 'top 62%',
        end: 'bottom 38%',
        onEnter: () => setStage(index),
        onEnterBack: () => setStage(index),
      });
    });
  }

  scrollToJourney(): void {
    const target = this.journeyRoot?.nativeElement;
    if (!target || !isPlatformBrowser(this.platformId)) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      target.scrollIntoView();
      return;
    }
    gsap.registerPlugin(ScrollToPlugin, ScrollTrigger);
    gsap.to(window, { duration: 0.75, scrollTo: { y: target, offsetY: 76 }, ease: 'power3.inOut' });
  }

  scrollToTopAndUpload(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.scrollTo({ top: 0 });
      return;
    }
    gsap.registerPlugin(ScrollToPlugin, ScrollTrigger);
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
    this.dashboardState.reset();
    this.ingestionState.beginImport(this.localFile, 'INITIAL');

    this.apiService.uploadCsvV2(this.localFile, this.apiService.getCurrentWorkspaceId(), 'INITIAL').subscribe({
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
          this.ingestionState.setDatasetStatus('profiling', 'Tệp đã được kiểm tra. Cần xác nhận ánh xạ cột trước khi nhập dữ liệu.');
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

}
