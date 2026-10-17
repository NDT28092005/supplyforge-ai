import { Injectable, PLATFORM_ID, inject } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { gsap } from 'gsap';

/**
 * Keeps operational motion consistent across the app and honours users who
 * disable animation at OS level. Numbers and data themselves are never tweened.
 */
@Injectable({ providedIn: 'root' })
export class PageMotionService {
  private readonly platformId = inject(PLATFORM_ID);

  reveal(root: HTMLElement): () => void {
    if (!isPlatformBrowser(this.platformId) || this.prefersReducedMotion()) {
      return () => undefined;
    }

    const context = gsap.context(() => {
      const header = root.querySelectorAll<HTMLElement>('[data-motion="header"]');
      const priority = root.querySelectorAll<HTMLElement>('[data-motion="priority"]');
      const panels = root.querySelectorAll<HTMLElement>('[data-motion="panel"]');
      const table = root.querySelectorAll<HTMLElement>('[data-motion="table"]');

      const timeline = gsap.timeline({ defaults: { ease: 'power3.out' } });
      if (header.length) {
        timeline.fromTo(header, { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.32 });
      }
      if (priority.length) {
        timeline.fromTo(
          priority,
          { autoAlpha: 0, y: 8 },
          { autoAlpha: 1, y: 0, duration: 0.28, stagger: 0.055 },
          header.length ? '-=0.12' : 0,
        );
      }
      if (panels.length) {
        timeline.fromTo(
          panels,
          { autoAlpha: 0, y: 8 },
          { autoAlpha: 1, y: 0, duration: 0.28, stagger: 0.035 },
          '-=0.12',
        );
      }
      if (table.length) {
        timeline.fromTo(table, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.24 }, '-=0.08');
      }
    }, root);

    return () => context.revert();
  }

  animateProgress(element: HTMLElement, value: number): void {
    if (!isPlatformBrowser(this.platformId) || this.prefersReducedMotion()) {
      element.style.width = `${value}%`;
      return;
    }
    gsap.to(element, { width: `${value}%`, duration: 0.45, ease: 'power2.out', overwrite: 'auto' });
  }

  private prefersReducedMotion(): boolean {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }
}
