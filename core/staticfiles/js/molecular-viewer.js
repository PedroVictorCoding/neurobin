// Molecular Viewer using SmilesDrawer
class MolecularViewer {
  constructor() {
    this.drawer = null;
    this.isInitialized = false;
  }

  // Initialize SmilesDrawer with settings
  init(settings = {}) {
    if (typeof SmilesDrawer === 'undefined') {
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
      compactDrawing: true,
      fontSizeLarge: 12,
      fontSizeSmall: 10,
      padding: 10,
      experimental: false,
      themes: {
        dark: {
          C: '#ffffff',
          O: '#ff4757',
          N: '#3742fa',
          F: '#7bed9f',
          CL: '#70a1ff',
          BR: '#5f27cd',
          I: '#341f97',
          P: '#ff6348',
          S: '#ffa502',
          B: '#ff9ff3',
          SI: '#636e72',
          H: '#ddd',
          BACKGROUND: '#2a2a2a'
        }
      }
    };

    const config = Object.assign({}, defaultSettings, settings);
    this.drawer = new SmilesDrawer.SvgDrawer(config);
    this.isInitialized = true;
    return true;
  }

  // Draw a single molecule
  drawMolecule(smiles, targetElement, theme = 'dark') {
    if (!this.isInitialized) {
      console.error('MolecularViewer not initialized');
      return false;
    }

    return new Promise((resolve, reject) => {
      SmilesDrawer.parse(smiles, (tree) => {
        try {
          this.drawer.draw(tree, targetElement, theme, false);
          
          // Apply styling
          if (typeof targetElement === 'string') {
            const svg = document.getElementById(targetElement);
            if (svg) {
              svg.style.backgroundColor = '#2a2a2a';
              svg.style.borderRadius = '8px';
            }
          } else {
            targetElement.style.backgroundColor = '#2a2a2a';
            targetElement.style.borderRadius = '8px';
          }
          
          resolve(true);
        } catch (error) {
          reject(error);
        }
      }, (err) => {
        reject(err);
      });
    });
  }

  // Draw all molecules in a container
  drawAllMolecules(containerSelector = '.molecule-viewer') {
    if (!this.isInitialized) {
      console.error('MolecularViewer not initialized');
      return;
    }

    const moleculeViewers = document.querySelectorAll(containerSelector);
    
    moleculeViewers.forEach((svg, index) => {
      const smiles = svg.getAttribute('data-smiles');
      if (!smiles) return;

      console.log(`Drawing molecule ${index + 1}:`, smiles);
      
      this.drawMolecule(smiles, svg)
        .then(() => {
          console.log(`Successfully drew molecule ${index + 1}`);
        })
        .catch((err) => {
          console.error(`Failed to draw molecule ${index + 1}:`, err);
          this.showFallback(svg);
        });
    });
  }

  // Show fallback for failed molecules
  showFallback(svg) {
    const container = svg.parentElement;
    if (container) {
      // Check if this is a detail view (larger container)
      const isDetailView = container.id === 'moleculeContainer';
      
      if (isDetailView) {
        container.innerHTML = `
          <div class="text-center p-3">
            <div class="text-warning small mb-2">
              <i class="fas fa-exclamation-triangle"></i> Structure Loading Failed
            </div>
            <div class="text-light small fw-bold mb-1">Molecular Structure</div>
            <div class="text-secondary" style="font-size: 9px; word-break: break-all; line-height: 1.3; font-family: monospace;">
              Unable to render structure
            </div>
          </div>
        `;
      } else {
        // List view fallback
        container.innerHTML = `
          <div class="text-center p-1" style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;">
            <div class="text-warning" style="font-size: 10px;">
              <i class="fas fa-exclamation-triangle"></i>
            </div>
          </div>
        `;
      }
    }
  }
}

// Global molecular viewer instance
window.molecularViewer = new MolecularViewer();

// Initialize when DOM and SmilesDrawer are ready
document.addEventListener('DOMContentLoaded', function() {
  // Wait for SmilesDrawer to load
  const checkSmilesDrawer = () => {
    if (typeof SmilesDrawer !== 'undefined') {
      // Initialize for compound list (small thumbnails)
      if (document.querySelector('.molecule-viewer')) {
        window.molecularViewer.init({
          width: 58,
          height: 58,
          bondThickness: 1.5,
          bondLength: 15,
          shortBondLength: 0.85,
          bondSpacing: 0.18 * 15,
          fontSizeLarge: 8,
          fontSizeSmall: 6,
          padding: 4
        });
        window.molecularViewer.drawAllMolecules();
      }
      
      // Initialize for compound detail (large view)
      if (document.getElementById('moleculeViewer')) {
        const detailViewer = new MolecularViewer();
        detailViewer.init(); // Use default settings for detail view
        
        const compoundSmiles = document.getElementById('moleculeViewer').getAttribute('data-smiles');
        if (compoundSmiles) {
          detailViewer.drawMolecule(compoundSmiles, 'moleculeViewer')
            .catch((err) => {
              console.error('Failed to draw compound detail molecule:', err);
              detailViewer.showFallback(document.getElementById('moleculeViewer'));
            });
        }
      }
    } else {
      setTimeout(checkSmilesDrawer, 100);
    }
  };
  
  checkSmilesDrawer();
});
