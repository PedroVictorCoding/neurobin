/**
 * Effect Curve Visualization
 * Uses Chart.js to render compound effect curves over time
 */

class EffectCurveChart {
    constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.chart = null;
        this.options = {
            responsive: true,
            maintainAspectRatio: false,
            height: options.height || 400,
            showRelativeTime: options.showRelativeTime || false,
            maxDoseReference: options.maxDoseReference || {},
            ...options
        };
        
        this.initChart();
    }
    
    initChart() {
        const defaultOptions = {
            type: 'line',
            data: {
                datasets: []
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                scales: {
                    x: {
                        type: 'linear',
                        display: true,
                        title: {
                            display: true,
                            text: this.options.showRelativeTime ? 'Time (T+00:00)' : 'Time (minutes)'
                        },
                        ticks: {
                            callback: (value) => {
                                if (this.options.showRelativeTime) {
                                    const hours = Math.floor(value / 60);
                                    const minutes = value % 60;
                                    return `T+${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                }
                                return `${value}m`;
                            }
                        }
                    },
                    y: {
                        display: true,
                        title: {
                            display: true,
                            text: 'Effect Intensity (%)'
                        },
                        min: 0,
                        max: 100,
                        ticks: {
                            callback: (value) => `${value}%`
                        }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Effect Curves Over Time'
                    },
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            title: (context) => {
                                const value = context[0].parsed.x;
                                if (this.options.showRelativeTime) {
                                    const hours = Math.floor(value / 60);
                                    const minutes = value % 60;
                                    return `T+${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                }
                                return `${value} minutes`;
                            },
                            label: (context) => {
                                const datasetLabel = context.dataset.label || '';
                                const value = Math.round(context.parsed.y * 10) / 10;
                                return `${datasetLabel}: ${value}%`;
                            }
                        }
                    }
                }
            }
        };
        
        this.chart = new Chart(this.ctx, defaultOptions);
    }
    
    /**
     * Add a single effect curve to the chart
     * @param {Object} effectData - Effect window data from API
     * @param {Object} intakeData - Optional intake data for dose scaling
     */
    addEffectCurve(effectData, intakeData = null) {
        const color = this.generateColor(this.chart.data.datasets.length);
        let scaledCurveData = effectData.effect_curve_data;
        
        // Scale curve based on dose if intake data provided
        if (intakeData && this.options.maxDoseReference[effectData.compound.id]) {
            const maxDose = this.options.maxDoseReference[effectData.compound.id];
            const currentDose = parseFloat(intakeData.amount) || 1;
            const scaleFactor = currentDose / maxDose;
            
            scaledCurveData = effectData.effect_curve_data.map(([time, intensity]) => [
                time,
                Math.min(100, intensity * scaleFactor)
            ]);
        }
        
        // Convert to Chart.js format
        const chartData = scaledCurveData.map(([time, intensity]) => ({
            x: time,
            y: intensity
        }));
        
        const dataset = {
            label: `${effectData.compound.name}${intakeData ? ` (${intakeData.amount}${intakeData.unit})` : ''}`,
            data: chartData,
            borderColor: color,
            backgroundColor: color + '20', // Add transparency
            borderWidth: 2,
            fill: false,
            tension: 0.1,
            pointRadius: 1,
            pointHoverRadius: 5,
            metadata: {
                compound: effectData.compound,
                effectWindow: effectData,
                intake: intakeData
            }
        };
        
        this.chart.data.datasets.push(dataset);
        this.chart.update();
    }
    
    /**
     * Add multiple effect curves from intake logs
     * @param {Array} intakeLogs - Array of intake log objects with effect_window data
     * @param {Date} referenceDate - Reference date for time calculations
     */
    addIntakeCurves(intakeLogs, referenceDate = null) {
        intakeLogs.forEach((intake, index) => {
            if (!intake.compound.effect_windows || intake.compound.effect_windows.length === 0) {
                console.warn(`No effect window data for compound: ${intake.compound.name}`);
                return;
            }
            
            // Use the first effect window (could be enhanced to select best match)
            const effectWindow = intake.compound.effect_windows[0];
            
            // Calculate time offset if reference date provided
            let timeOffset = 0;
            if (referenceDate && intake.taken_at) {
                const intakeTime = new Date(intake.taken_at);
                timeOffset = Math.floor((intakeTime - referenceDate) / (1000 * 60)); // Minutes difference
            }
            
            // Adjust curve data for time offset
            const adjustedCurveData = effectWindow.effect_curve_data.map(([time, intensity]) => [
                time + timeOffset,
                intensity
            ]);
            
            const adjustedEffectWindow = {
                ...effectWindow,
                effect_curve_data: adjustedCurveData
            };
            
            this.addEffectCurve(adjustedEffectWindow, intake);
        });
    }
    
    /**
     * Clear all curves from the chart
     */
    clearCurves() {
        this.chart.data.datasets = [];
        this.chart.update();
    }
    
    /**
     * Update chart title
     */
    setTitle(title) {
        this.chart.options.plugins.title.text = title;
        this.chart.update();
    }
    
    /**
     * Generate a color for the curve
     */
    generateColor(index) {
        const colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
            '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF',
            '#4BC0C0', '#36A2EB', '#FFCE56'
        ];
        return colors[index % colors.length];
    }
    
    /**
     * Destroy the chart
     */
    destroy() {
        if (this.chart) {
            this.chart.destroy();
        }
    }
}

/**
 * API helper functions for fetching effect data
 */
class EffectDataAPI {
    constructor(baseUrl = '/api') {
        this.baseUrl = baseUrl;
    }
    
    /**
     * Fetch effect windows for a compound
     */
    async getCompoundEffectWindows(compoundId) {
        try {
            const response = await fetch(`${this.baseUrl}/compounds/effectwindow/?compound=${compoundId}`);
            if (!response.ok) throw new Error('Failed to fetch effect windows');
            return await response.json();
        } catch (error) {
            console.error('Error fetching effect windows:', error);
            return { results: [] };
        }
    }
    
    /**
     * Fetch intake logs with compound data
     */
    async getIntakeLogs(params = {}) {
        try {
            const queryString = new URLSearchParams(params).toString();
            const response = await fetch(`${this.baseUrl}/logs/intakelog/?${queryString}`);
            if (!response.ok) throw new Error('Failed to fetch intake logs');
            return await response.json();
        } catch (error) {
            console.error('Error fetching intake logs:', error);
            return { results: [] };
        }
    }
    
    /**
     * Get curve data with custom resolution
     */
    async getDetailedCurveData(effectWindowId, resolution = 5) {
        try {
            const response = await fetch(`${this.baseUrl}/compounds/effectwindow/${effectWindowId}/curve_data/?resolution=${resolution}`);
            if (!response.ok) throw new Error('Failed to fetch curve data');
            return await response.json();
        } catch (error) {
            console.error('Error fetching curve data:', error);
            return null;
        }
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { EffectCurveChart, EffectDataAPI };
}
