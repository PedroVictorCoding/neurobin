// Molecular viewer utility for React components
class MolecularViewer {
  constructor() {
    this.drawer = null;
    this.isInitialized = false;
  }

  // Initialize SmilesDrawer with settings
  init(settings = {}) {
    if (typeof window === 'undefined' || typeof window.SmilesDrawer === 'undefined') {
      console.error('SmilesDrawer not loaded');
      return false;
    }

    const defaultSettings = {
      width: 196,
      height: 196,
      bondThickness: 2,
      bondLength: 20,
      shortBondLength: 0.85,
      bondSpacing: 0.18 * 20,
      atomVisualization: 'default',
      isomeric: true,
      debug: false,
      terminalCarbons: false,
      explicitHydrogens: false,
      overlapSensitivity: 0.42,
      overlapResolutionIterations: 1,
      compactDrawing: false,
      fontFamily: 'Arial, Helvetica, sans-serif',
      fontSizeLarge: 5,
      fontSizeSmall: 3,
      padding: 20.0,
      experimentalSSSR: true,
      kkThreshold: 0.1,
      kkInnerThreshold: 0.1,
      kkMaxIteration: 20000,
      kkMaxInnerIteration: 50,
      kkMaxEnergy: 1e9
    };

    const finalSettings = { ...defaultSettings, ...settings };
    
    try {
      this.drawer = new window.SmilesDrawer.Drawer(finalSettings);
      this.isInitialized = true;
      console.log('SmilesDrawer initialized successfully');
      return true;
    } catch (error) {
      console.error('Failed to initialize SmilesDrawer:', error);
      return false;
    }
  }

  // Draw a single molecule
  drawMolecule(smiles, targetElement, customSettings = {}) {
    return new Promise((resolve, reject) => {
      if (!this.isInitialized) {
        if (!this.init(customSettings)) {
          reject(new Error('Failed to initialize SmilesDrawer'));
          return;
        }
      }

      if (!smiles || smiles.trim() === '') {
        reject(new Error('Empty SMILES string'));
        return;
      }

      const cleanSmiles = smiles.trim();
      console.log('Drawing molecule with SMILES:', cleanSmiles);

      try {
        const theme = window.SmilesDrawer.Themes.dark;
        
        window.SmilesDrawer.parse(cleanSmiles, (tree) => {
          try {
            this.drawer.draw(tree, targetElement, theme, false);
            
            // Apply styling
            let svg;
            if (typeof targetElement === 'string') {
              svg = document.getElementById(targetElement);
            } else {
              svg = targetElement;
            }
            
            if (svg) {
              svg.style.backgroundColor = '#2a2a2a';
              svg.style.borderRadius = '8px';
            }
            
            console.log('Successfully drew molecule:', cleanSmiles);
            resolve(true);
          } catch (error) {
            console.error('Error drawing molecule:', error);
            reject(error);
          }
        }, (parseError) => {
          console.error('Error parsing SMILES:', parseError, 'for SMILES:', cleanSmiles);
          reject(parseError);
        });
      } catch (outerError) {
        console.error('Outer error in drawMolecule:', outerError);
        reject(outerError);
      }
    });
  }

  // Draw all molecules in a container
  drawAllMolecules(containerSelector = '.molecule-viewer') {
    if (!this.isInitialized) {
      console.error('MolecularViewer not initialized');
      return;
    }

    const moleculeViewers = document.querySelectorAll(containerSelector);
    console.log(`Found ${moleculeViewers.length} molecule viewers to process`);
    
    moleculeViewers.forEach((svg, index) => {
      const smiles = svg.getAttribute('data-smiles');
      if (!smiles) {
        console.warn(`No SMILES data for molecule viewer ${index + 1}`);
        return;
      }

      console.log(`Processing molecule ${index + 1}:`, smiles);
      
      this.drawMolecule(smiles, svg)
        .then(() => {
          console.log(`Successfully processed molecule ${index + 1}`);
        })
        .catch(error => {
          console.error(`Failed to process molecule ${index + 1}:`, error);
        });
    });
  }

  // Initialize and draw all molecules (convenience method)
  initAndDrawAll(containerSelector = '.molecule-viewer', settings = {}) {
    if (!this.isInitialized) {
      if (!this.init(settings)) {
        console.error('Failed to initialize molecular viewer');
        return;
      }
    }
    
    // Small delay to ensure DOM is ready
    setTimeout(() => {
      this.drawAllMolecules(containerSelector);
    }, 100);
  }
}

// Create a global instance
let globalMolecularViewer = null;

// Utility functions for React components
export const initMolecularViewer = (settings = {}) => {
  if (!globalMolecularViewer) {
    globalMolecularViewer = new MolecularViewer();
  }
  return globalMolecularViewer.init(settings);
};

export const drawMolecule = (smiles, targetElement, settings = {}) => {
  if (!globalMolecularViewer) {
    globalMolecularViewer = new MolecularViewer();
  }
  return globalMolecularViewer.drawMolecule(smiles, targetElement, settings);
};

export const drawAllMolecules = (containerSelector = '.molecule-viewer') => {
  if (!globalMolecularViewer) {
    globalMolecularViewer = new MolecularViewer();
  }
  globalMolecularViewer.drawAllMolecules(containerSelector);
};

export const initAndDrawAll = (containerSelector = '.molecule-viewer', settings = {}) => {
  if (!globalMolecularViewer) {
    globalMolecularViewer = new MolecularViewer();
  }
  globalMolecularViewer.initAndDrawAll(containerSelector, settings);
};

export default MolecularViewer;
