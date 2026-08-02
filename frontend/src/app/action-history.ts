import { MatchProposal } from './match-proposal';

export interface ActionHistory {
  type: 'merge' | 'ignore';
  proposal: MatchProposal;
}
