import { BrowserRouter as Router, Routes, Route } from 'react-router';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import theme from './theme';
import Home from './pages/Home';
import RaceMode from './pages/RaceMode';

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Router>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/live-stream/:streamId" element={<RaceMode />} />
        </Routes>
      </Router>
    </ThemeProvider>
  );
}

export default App;

