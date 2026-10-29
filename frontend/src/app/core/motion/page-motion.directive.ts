import { AfterViewChecked, AfterViewInit, Directive, ElementRef, OnDestroy, inject } from '@angular/core';
import { PageMotionService } from './page-motion.service';

@Directive({
  selector: '[sfPageMotion]',
  standalone: true,
})
export class PageMotionDirective implements AfterViewInit, AfterViewChecked, OnDestroy {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly motion = inject(PageMotionService);
  private dispose?: () => void;
  private revealScheduled = false;
  private revealed = false;
  private destroyed = false;

  ngAfterViewInit(): void {
    this.scheduleReveal();
  }

  ngAfterViewChecked(): void {
    this.scheduleReveal();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.dispose?.();
  }

  private scheduleReveal(): void {
    if (this.revealed || this.revealScheduled) return;

    const root = this.host.nativeElement;
    if (!root.querySelector('[data-motion]')) return;

    this.revealScheduled = true;
    queueMicrotask(() => {
      this.revealScheduled = false;
      if (this.destroyed || this.revealed || !root.querySelector('[data-motion]')) return;

      this.dispose = this.motion.reveal(root);
      this.revealed = true;
    });
  }
}
