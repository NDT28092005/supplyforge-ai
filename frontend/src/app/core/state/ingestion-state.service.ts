import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export type DatasetLifecycleStatus =
  | 'idle'
  | 'clearing'
  | 'uploading'
  | 'profiling'
  | 'processing'
  | 'ready'
  | 'error';

export interface IngestionState {
  uploadFile: File | null;
  activeSessionId: string;
  mappingData: any | null;
  datasetProfileData: any | null;
  uploadErrorMessage: string;
  isProcessingBatch: boolean;
  sessionType: 'INITIAL' | 'INCREMENTAL';
  datasetStatus: DatasetLifecycleStatus;
  datasetStatusMessage: string;
}

const initialState: IngestionState = {
  uploadFile: null,
  activeSessionId: '',
  mappingData: null,
  datasetProfileData: null,
  uploadErrorMessage: '',
  isProcessingBatch: false,
  sessionType: 'INITIAL',
  datasetStatus: 'idle',
  datasetStatusMessage: ''
};

// Version the browser cache whenever an ingestion state format or lifecycle
// fix makes an older persisted session unsafe to resume.
const STORAGE_KEY = 'supplyforge_ingestion_state_v2';

function getPersistedState(): IngestionState {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      const savedStatus = parsed.datasetStatus as DatasetLifecycleStatus | undefined;
      // A browser refresh cannot resume an in-flight request safely. Keep the
      // persisted session for recovery, but never present old data as current.
      const interrupted = ['clearing', 'uploading', 'profiling', 'processing'].includes(savedStatus || 'idle');
      return {
        ...initialState,
        activeSessionId: parsed.activeSessionId || '',
        mappingData: parsed.mappingData || null,
        datasetProfileData: parsed.datasetProfileData || null,
        sessionType: parsed.sessionType === 'INCREMENTAL' ? 'INCREMENTAL' : 'INITIAL',
        datasetStatus: interrupted ? 'error' : (savedStatus || 'idle'),
        datasetStatusMessage: interrupted
          ? 'Phiên nạp dữ liệu đã bị gián đoạn. Vui lòng kiểm tra lại tệp và thực hiện lại thao tác.'
          : (parsed.datasetStatusMessage || ''),
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
        datasetProfileData: newState.datasetProfileData,
        sessionType: newState.sessionType,
        datasetStatus: newState.datasetStatus,
        datasetStatusMessage: newState.datasetStatusMessage
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
    this.persist({
      ...this.state,
      uploadErrorMessage: msg,
      datasetStatus: msg ? 'error' : this.state.datasetStatus,
      datasetStatusMessage: msg || this.state.datasetStatusMessage
    });
  }

  setProcessingBatch(isProcessing: boolean) {
    this.persist({ ...this.state, isProcessingBatch: isProcessing });
  }

  setSessionType(sessionType: 'INITIAL' | 'INCREMENTAL') {
    this.persist({ ...this.state, sessionType });
  }

  beginImport(file: File, sessionType: 'INITIAL' | 'INCREMENTAL') {
    this.persist({
      ...initialState,
      uploadFile: file,
      sessionType,
      datasetStatus: 'uploading',
      datasetStatusMessage: 'Đang tải tệp lên và kiểm tra cấu trúc dữ liệu.'
    });
  }

  setDatasetStatus(status: DatasetLifecycleStatus, message = '') {
    this.persist({
      ...this.state,
      datasetStatus: status,
      datasetStatusMessage: message,
      uploadErrorMessage: status === 'error' ? (message || this.state.uploadErrorMessage) : ''
    });
  }

  get isDatasetTransitionActive(): boolean {
    return ['clearing', 'uploading', 'profiling', 'processing'].includes(this.state.datasetStatus);
  }

  invalidateSession(message: string) {
    this.persist({
      ...initialState,
      datasetStatus: 'error',
      datasetStatusMessage: message,
      uploadErrorMessage: message
    });
  }

  reset() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
    this.state$.next(initialState);
  }
}
