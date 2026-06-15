'use client';

import dynamic from 'next/dynamic';
import { AppDialogProvider } from '../components/AppDialogProvider';

const App = dynamic(() => import('../App'), { ssr: false });

export default function Page() {
  return (
    <div id="root" style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppDialogProvider>
        <App />
      </AppDialogProvider>
    </div>
  );
}
