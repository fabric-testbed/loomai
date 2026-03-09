'use client';

import dynamic from 'next/dynamic';

const App = dynamic(() => import('../App'), { ssr: false });

export default function Page() {
  return (
    <div id="root" style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <App />
    </div>
  );
}
