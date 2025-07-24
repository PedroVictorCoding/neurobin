/**
 * Global compound color manager for consistent colors across all charts
 */
window.CompoundColorManager = {
    compoundColors: new Map(),
    
    /**
     * Get or assign a color for a compound name
     */
    getColorForCompound(compoundName) {
        // Normalize compound name for consistency
        const normalizedName = compoundName.trim().toLowerCase();
        
        if (!this.compoundColors.has(normalizedName)) {
            // Instead of using hash, assign colors sequentially to ensure uniqueness
            const assignedColors = Array.from(this.compoundColors.values());
            const color = this.getNextAvailableColor(assignedColors);
            this.compoundColors.set(normalizedName, color);
            console.log(`Global color manager assigned color ${color} to compound ${compoundName}`); // Debug log
        }
        return this.compoundColors.get(normalizedName);
    },

    /**
     * Get the next available color that hasn't been assigned yet
     */
    getNextAvailableColor(assignedColors) {
        const colors = [
            '#FF6384', // Red/Pink
            '#36A2EB', // Blue  
            '#FFCE56', // Yellow
            '#4BC0C0', // Teal
            '#9966FF', // Purple
            '#FF9F40', // Orange
            '#FF6B9D', // Pink
            '#2ECC71', // Green
            '#E74C3C', // Red
            '#3498DB', // Light Blue
            '#F39C12', // Orange
            '#9B59B6', // Purple
            '#1ABC9C', // Turquoise
            '#E67E22', // Dark Orange
            '#34495E', // Dark Gray
            '#16A085', // Dark Teal
            '#27AE60', // Dark Green
            '#8E44AD', // Dark Purple
            '#2980B9', // Dark Blue
            '#D35400', // Burnt Orange
            '#C0392B', // Dark Red
            '#8B4513', // Saddle Brown
            '#556B2F', // Dark Olive Green
            '#4B0082', // Indigo
            '#DC143C', // Crimson
            '#FF1493', // Deep Pink
            '#00CED1', // Dark Turquoise
            '#FF4500', // Red Orange
            '#32CD32', // Lime Green
            '#BA55D3'  // Medium Orchid
        ];
        
        // Find the first color that hasn't been assigned
        for (const color of colors) {
            if (!assignedColors.includes(color)) {
                return color;
            }
        }
        
        // If all predefined colors are used, generate a random color
        return this.generateRandomColor();
    },

    /**
     * Generate a random color when all predefined colors are exhausted
     */
    generateRandomColor() {
        const hue = Math.floor(Math.random() * 360);
        const saturation = 70 + Math.floor(Math.random() * 30); // 70-100%
        const lightness = 45 + Math.floor(Math.random() * 20);  // 45-65%
        return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    },

    /**
     * Get all assigned compound colors (for debugging)
     */
    getAllCompoundColors() {
        return Object.fromEntries(this.compoundColors);
    }
};

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
                plugins: {
                    zoom: {
                        zoom: {
                            wheel: {
                                enabled: !this.options.showRelativeTime, // Only enable zoom for timeline view (analytics dashboard)
                            },
                            pinch: {
                                enabled: !this.options.showRelativeTime // Only enable zoom for timeline view (analytics dashboard)
                            },
                            mode: 'x', // Only zoom on x-axis (time)
                            scaleMode: 'x', // Only scale x-axis
                        },
                        pan: {
                            enabled: !this.options.showRelativeTime, // Only enable pan for timeline view (analytics dashboard)
                            mode: 'x', // Only pan on x-axis
                            scaleMode: 'x',
                        },
                        limits: {
                            x: {
                                min: 0,    // 00:00 (start of day)
                                max: 1440, // 24:00 (end of day - 1440 minutes)
                                minRange: 60 // Minimum zoom range of 1 hour (60 minutes)
                            }
                        }
                    },
                    title: {
                        display: true,
                        text: 'Effect Curves Over Time'
                    },
                    legend: {
                        display: false, // Disable the chart legend
                        position: 'top'
                    },
                    tooltip: {
                        enabled: true, // Enable tooltips to show compound info
                        mode: 'nearest',
                        intersect: false,
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: 'white',
                        bodyColor: 'white',
                        borderColor: 'rgba(255, 255, 255, 0.2)',
                        borderWidth: 1,
                        callbacks: {
                            title: (context) => {
                                const value = context[0].parsed.x;
                                if (this.options.showRelativeTime) {
                                    const hours = Math.floor(value / 60);
                                    const minutes = value % 60;
                                    return `T+${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                } else {
                                    // Convert minutes from midnight to HH:MM format
                                    const totalMinutes = Math.floor(value);
                                    const hours = Math.floor(totalMinutes / 60) % 24;
                                    const minutes = totalMinutes % 60;
                                    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                }
                            },
                            label: (context) => {
                                const dataset = context.dataset;
                                const compoundName = dataset.metadata?.compound?.name || 'Unknown Compound';
                                const value = Math.round(context.parsed.y * 10) / 10;
                                
                                // Show compound name and dose if available
                                let label = `${compoundName}: ${value}%`;
                                if (dataset.metadata?.intake) {
                                    const intake = dataset.metadata.intake;
                                    label += ` (${intake.amount}${intake.unit})`;
                                }
                                
                                return label;
                            },
                            afterLabel: (context) => {
                                // Add additional compound info if available
                                const compound = context.dataset.metadata?.compound;
                                if (compound?.description) {
                                    const description = compound.description;
                                    if (description.length > 100) {
                                        return `${description.substring(0, 100)}...`;
                                    }
                                    return description;
                                }
                                return null;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'linear',
                        display: true,
                        title: {
                            display: true,
                            text: this.options.showRelativeTime ? 'Time (T+00:00)' : 'Time of Day'
                        },
                        ticks: {
                            callback: (value) => {
                                if (this.options.showRelativeTime) {
                                    const hours = Math.floor(value / 60);
                                    const minutes = value % 60;
                                    return `T+${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                } else {
                                    // Convert minutes from midnight to HH:MM format
                                    const totalMinutes = Math.floor(value);
                                    const hours = Math.floor(totalMinutes / 60) % 24;
                                    const minutes = totalMinutes % 60;
                                    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                }
                            }
                        },
                        min: this.options.showRelativeTime ? 0 : 0, // Start from 00:00 for timeline
                        max: this.options.showRelativeTime ? undefined : 1440 // 24 hours = 1440 minutes
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
        const compoundName = effectData.compound.name;
        const color = this.getColorForCompound(compoundName);
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
        
        // Ensure the curve has a data point at duration_minutes with 0% intensity
        const durationMinutes = effectData.duration_minutes;
        const lastDataPoint = scaledCurveData[scaledCurveData.length - 1];
        
        if (!lastDataPoint || lastDataPoint[0] < durationMinutes) {
            scaledCurveData.push([durationMinutes, 0]);
        } else if (lastDataPoint[0] === durationMinutes && lastDataPoint[1] !== 0) {
            // Ensure the last point is at 0% intensity
            scaledCurveData[scaledCurveData.length - 1][1] = 0;
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
            backgroundColor: color + '30', // Semitransparent fill (30% opacity)
            borderWidth: 2,
            fill: true, // Enable fill area under the curve
            tension: 0.1,
            pointRadius: 0, // Start with data points hidden
            pointHoverRadius: 0, // Start with hover disabled
            metadata: {
                compound: effectData.compound,
                effectWindow: effectData,
                intake: intakeData
            }
        };
        
        this.chart.data.datasets.push(dataset);
        
        // Update x-axis to show full duration
        this.updateXAxisRange();
        
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
            
            // Calculate time offset 
            let timeOffset = 0;
            if (intake.taken_at) {
                // Parse the datetime string - Django sends ISO format with timezone
                let intakeTime = new Date(intake.taken_at);
                console.log(`Original taken_at: ${intake.taken_at}`); // Debug log
                console.log(`Parsed intakeTime: ${intakeTime}`); // Debug log
                console.log(`toString(): ${intakeTime.toString()}`); // Debug log
                console.log(`toISOString(): ${intakeTime.toISOString()}`); // Debug log
                console.log(`Local time: ${intakeTime.getHours()}:${String(intakeTime.getMinutes()).padStart(2, '0')}`); // Debug log
                console.log(`UTC time: ${intakeTime.getUTCHours()}:${String(intakeTime.getUTCMinutes()).padStart(2, '0')}`); // Debug log
                console.log(`Timezone offset (minutes): ${intakeTime.getTimezoneOffset()}`); // Debug log
                
                if (this.options.showRelativeTime) {
                    // For relative time, calculate minutes from reference date
                    if (referenceDate) {
                        timeOffset = Math.floor((intakeTime - referenceDate) / (1000 * 60));
                    }
                } else {
                    // For timeline, use UTC time to match Django's storage format
                    // This ensures consistent display regardless of browser timezone
                    // TODO: Consider adding user timezone preference in the future
                    timeOffset = intakeTime.getUTCHours() * 60 + intakeTime.getUTCMinutes();
                    console.log(`Original intake time string: ${intake.taken_at}`); // Debug log
                    console.log(`Parsed as Date: ${intakeTime.toString()}`); // Debug log
                    console.log(`UTC hours: ${intakeTime.getUTCHours()}, minutes: ${intakeTime.getUTCMinutes()}`); // Debug log
                    console.log(`Local hours: ${intakeTime.getHours()}, minutes: ${intakeTime.getMinutes()}`); // Debug log
                    console.log(`Using UTC time - Calculated timeOffset: ${timeOffset} minutes = ${Math.floor(timeOffset/60)}:${String(timeOffset%60).padStart(2, '0')}`); // Debug log
                }
                console.log(`Calculated timeOffset: ${timeOffset} minutes from midnight`); // Debug log
            }
            
            // Adjust curve data for time offset
            const adjustedCurveData = effectWindow.effect_curve_data.map(([time, intensity]) => [
                time + timeOffset,
                intensity
            ]);
            
            const adjustedEffectWindow = {
                ...effectWindow,
                effect_curve_data: adjustedCurveData,
                duration_minutes: effectWindow.duration_minutes + timeOffset,
                compound: intake.compound // Ensure compound reference is correct
            };
            
            this.addEffectCurve(adjustedEffectWindow, intake);
        });
        
        // Update x-axis range after adding all curves
        this.updateXAxisRange();
    }    /**
     * Clear all curves from the chart
     */
    clearCurves() {
        this.chart.data.datasets = [];
        // Don't clear compound colors - keep them for consistency across reloads
        // this.compoundColors.clear(); 
        this.chart.update();
    }
    
    /**
     * Reset all data including compound colors (use sparingly)
     */
    resetChart() {
        this.chart.data.datasets = [];
        this.compoundColors.clear();
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
     * Update x-axis range to show full duration of all curves
     */
    updateXAxisRange() {
        if (!this.chart.data.datasets.length) return;
        
        if (this.options.showRelativeTime) {
            // For relative time (compound detail), find the maximum duration
            let maxDuration = 0;
            
            this.chart.data.datasets.forEach(dataset => {
                const effectWindow = dataset.metadata?.effectWindow;
                if (effectWindow && effectWindow.duration_minutes) {
                    maxDuration = Math.max(maxDuration, effectWindow.duration_minutes);
                }
                
                // Also check the actual data points
                dataset.data.forEach(point => {
                    maxDuration = Math.max(maxDuration, point.x);
                });
            });
            
            // Set x-axis max to the maximum duration with some padding
            if (maxDuration > 0) {
                this.chart.options.scales.x.max = maxDuration;
                this.chart.options.scales.x.min = 0;
            }
        } else {
            // For timeline view, show full day (00:00 to 23:59)
            this.chart.options.scales.x.min = 0;     // 00:00
            this.chart.options.scales.x.max = 1440;  // 24:00 (1440 minutes)
        }
    }
    
    /**
     * Get or assign a color for a compound name (uses global color manager)
     */
    getColorForCompound(compoundName) {
        return window.CompoundColorManager.getColorForCompound(compoundName);
    }
    
    /**
     * Generate a color for the curve (legacy method, now uses compound-based colors)
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
