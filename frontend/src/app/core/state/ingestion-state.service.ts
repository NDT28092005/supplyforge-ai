import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface IngestionState {
  uploadFile: File | null;
  activeSessionId: string;
  mappingData: any | null;
  datasetProfileData: any | null;
  uploadErrorMessage: string;
  isProcessingBatch: boolean;
}

const initialState: IngestionState = {
  uploadFile: null,
  activeSessionId: '',
  mappingData: null,
  datasetProfileData: null,
  uploadErrorMessage: '',
  isProcessingBatch: false
};

const STORAGE_KEY = 'supplyforge_ingestion_state';

function getPersistedState(): IngestionState {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        ...initialState,
        activeSessionId: parsed.activeSessionId || '',
        mappingData: parsed.mappingData || null,
        datasetProfileData: parsed.datasetProfileData || null,
      };
    }
  } catch (e) {
    console.warn('[IngestionState] Could not load from sessionStorage:', e);
  }
  return initialState;
}

@Injectable({
  providedIn: 'root'
})
export class IngestionStateService {
  private state$ = new BehaviorSubject<IngestionState>(getPersistedState());

  get state(): IngestionState {
    return this.state$.getValue();
  }

  get stateObservable() {
    return this.state$.asObservable();
  }

  private persist(newState: IngestionState) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        activeSessionId: newState.activeSessionId,
        mappingData: newState.mappingData,
        datasetProfileData: newState.datasetProfileData
      }));
    } catch (e) {}
    this.state$.next(newState);
  }

  setFile(file: File | null) {
    this.persist({ ...this.state, uploadFile: file });
  }

  setSessionId(sessionId: string) {
    this.persist({ ...this.state, activeSessionId: sessionId });
  }

  setMappingData(mappingData: any) {
    this.persist({ ...this.state, mappingData });
  }

  setProfileData(datasetProfileData: any) {
    this.persist({ ...this.state, datasetProfileData });
  }

  setErrorMessage(msg: string) {
    this.persist({ ...this.state, uploadErrorMessage: msg });
  }

  setProcessingBatch(isProcessing: boolean) {
    this.persist({ ...this.state, isProcessingBatch: isProcessing });
  }

  reset() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
    this.state$.next(initialState);
  }
}
