import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.jsx';
import '../styles.css';
import '../upgrade.css';
import '../reading.css';
import '../resizable.css';

createRoot(document.getElementById('app')).render(<React.StrictMode><App/></React.StrictMode>);

import '../workspace.css';
