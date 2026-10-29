import {afterEach, vi} from 'vitest';
import {cleanup} from '@testing-library/react';

Object.defineProperty(window,'scrollTo',{value:vi.fn(),writable:true});
HTMLDialogElement.prototype.showModal=function(){this.open=true;};
HTMLDialogElement.prototype.close=function(){this.open=false;};
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
