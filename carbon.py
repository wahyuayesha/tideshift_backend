"""
Carbon emission calculation functions with Fuzzy Logic integration
"""

import numpy as np
import skfuzzy as fuzz
from datetime import datetime, timedelta

# Emission factors for different activities (kg CO2)
EMISSION_FACTORS = {
    'carTravelKm': 0.21,
    'packagedFood': 0.5,
    'showerTimeMinutes': 0.05,
    'electronicTimeHours': 0.06,
    'onlineShopping': 1.0,
    'wasteFood': 0.9,
    'airConditioningHeating': 1.5,

    # Saved if true
    'noDriving': -1.0,
    'plantMealThanMeat': -2.0,
    'useTumbler': -0.2,
    'saveEnergy': -0.3,
    'separateRecycleWaste': -0.7
}


# Category mapping for emission levels
CATEGORY_MAPPING = {
    1: {"level": "very_low", "label": "Very Low (Ideal)", "emoji": "🌿"},
    2: {"level": "low", "label": "Low (Sustainable)", "emoji": "🟢"},
    3: {"level": "moderate", "label": "Moderate (Fairly good)", "emoji": "🟡"},
    4: {"level": "high", "label": "High (Needs improvement)", "emoji": "🟠"},
    5: {"level": "very_high", "label": "Very High (Requires attention)", "emoji": "🔴"}
}

# Default values for fuzzy logic
DEFAULT_VALUES = {
    'carTravelKm': 10,
    'showerTimeMinutes': 12,
    'electronicTimeHours': 8
}


def calculate_carbon_emissions(payload):
    """
    Calculate total carbon emissions from user activities
    
    Args:
        payload (dict): User activity data
    
    Returns:
        float: Total carbon emissions in kg CO2
    """
    negative_emissions = 0
    positive_reductions = 0

    for activity, factor in EMISSION_FACTORS.items():
        value = payload.get(activity, 0)
        if isinstance(value, bool):
            if value:
                if factor < 0:
                    positive_reductions += abs(factor)
                else:
                    negative_emissions += factor
        else:
            negative_emissions += float(value) * factor

    total_emissions = max(0, negative_emissions - positive_reductions)
    return total_emissions


def classify_level(total_emission):
    """
    Classify emission level based on total kg CO2
    
    Args:
        total_emission (float): Total emissions in kg CO2
    
    Returns:
        int: Level category (1-5)
    """
    if total_emission < 2.5:
        return 1  # Very Low
    elif total_emission < 5:
        return 2  # Low
    elif total_emission < 8:
        return 3  # Moderate
    elif total_emission < 12:
        return 4  # High
    else:
        return 5  # Very High

def get_emission_category(level):
    """
    Get emission category details
    
    Args:
        level (int): Level category (1-5)
    
    Returns:
        dict: Category information
    """
    return CATEGORY_MAPPING.get(level, CATEGORY_MAPPING[5])

class CarbonFuzzySystem:
    """
    Fuzzy Logic System for carbon emission suggestions
    """
    
    @staticmethod
    def calculate_normal_values(historical_data):
        """
        Calculate normal values from historical data
        
        Args:
            historical_data (list): List of DailyCarbonLog objects
        
        Returns:
            dict: Normal values for main activities
        """
        if len(historical_data) < 3:
            return DEFAULT_VALUES
        
        # Extract main activity data
        car_data = [log.carTravelKm or 0 for log in historical_data]
        shower_data = [log.showerTimeMinutes or 0 for log in historical_data]
        electronic_data = [log.electronicTimeHours or 0 for log in historical_data]
        
        # Calculate median
        car_data.sort()
        shower_data.sort()
        electronic_data.sort()
        
        middle = len(car_data) // 2
        
        return {
            'carTravelKm': car_data[middle],
            'showerTimeMinutes': shower_data[middle],
            'electronicTimeHours': electronic_data[middle]
        }
    

    @staticmethod
    def fuzzy_system_analysis(car_km, shower_min, electronic_hours, normal_values):
        try:
            # create value ranges
            max_car = max(50, normal_values['carTravelKm'] * 3)
            max_shower = max(30, normal_values['showerTimeMinutes'] * 3)
            max_electronic = max(24, normal_values['electronicTimeHours'] * 3)
            
            range_car = np.arange(0, max_car, 1)
            range_shower = np.arange(0, max_shower, 1)
            range_electronic = np.arange(0, max_electronic, 1)
            range_suggestion = np.arange(0, 21, 1)
            
            # membership functions for high usage
            car_high = fuzz.trimf(range_car, [
                normal_values['carTravelKm'] * 0.8,
                normal_values['carTravelKm'] * 1.2,
                normal_values['carTravelKm'] * 2
            ])
            shower_long = fuzz.trimf(range_shower, [
                normal_values['showerTimeMinutes'] * 0.8,
                normal_values['showerTimeMinutes'] * 1.2,
                normal_values['showerTimeMinutes'] * 2
            ])
            electronic_much = fuzz.trimf(range_electronic, [
                normal_values['electronicTimeHours'] * 0.8,
                normal_values['electronicTimeHours'] * 1.2,
                normal_values['electronicTimeHours'] * 2
            ])
            
            # suggestion functions
            suggestion_light = fuzz.trimf(range_suggestion, [2, 5, 8])
            suggestion_moderate = fuzz.trimf(range_suggestion, [4, 8, 12])
            suggestion_aggressive = fuzz.trimf(range_suggestion, [8, 12, 16])
            
            # membership degrees
            degree_car_high = fuzz.interp_membership(range_car, car_high, car_km)
            degree_shower_long = fuzz.interp_membership(range_shower, shower_long, shower_min)
            degree_electronic_much = fuzz.interp_membership(range_electronic, electronic_much, electronic_hours)
            
            # minimum limits (90% of normal)
            min_car = normal_values['carTravelKm'] * 0.9
            min_shower = normal_values['showerTimeMinutes'] * 0.9
            min_electronic = normal_values['electronicTimeHours'] * 0.9
            
            # --- car suggestions ---
            if car_km > normal_values['carTravelKm']:
                if degree_car_high > 0.6:
                    reduction = fuzz.defuzz(range_suggestion, suggestion_aggressive * degree_car_high, 'centroid')
                    suggested_car = max(min_car, car_km - (reduction * 0.6))
                elif degree_car_high > 0.3:
                    reduction = fuzz.defuzz(range_suggestion, suggestion_moderate * degree_car_high, 'centroid')
                    suggested_car = max(min_car, car_km - (reduction * 0.4))
                else:
                    suggested_car = car_km
            else:
                suggested_car = car_km  # already below normal
            
            # --- shower suggestions ---
            if shower_min > normal_values['showerTimeMinutes']:
                if degree_shower_long > 0.6:
                    reduction = fuzz.defuzz(range_suggestion, suggestion_aggressive * degree_shower_long, 'centroid')
                    suggested_shower = max(min_shower, shower_min - (reduction * 0.5))
                elif degree_shower_long > 0.3:
                    reduction = fuzz.defuzz(range_suggestion, suggestion_moderate * degree_shower_long, 'centroid')
                    suggested_shower = max(min_shower, shower_min - (reduction * 0.3))
                else:
                    suggested_shower = shower_min
            else:
                suggested_shower = shower_min
            
            # --- electronic suggestions ---
            if electronic_hours > normal_values['electronicTimeHours']:
                if degree_electronic_much > 0.6:
                    reduction = fuzz.defuzz(range_suggestion, suggestion_aggressive * degree_electronic_much, 'centroid')
                    suggested_electronic = max(min_electronic, electronic_hours - (reduction * 0.4))
                elif degree_electronic_much > 0.3:
                    reduction = fuzz.defuzz(range_suggestion, suggestion_moderate * degree_electronic_much, 'centroid')
                    suggested_electronic = max(min_electronic, electronic_hours - (reduction * 0.25))
                else:
                    suggested_electronic = electronic_hours
            else:
                suggested_electronic = electronic_hours
            
            # jangan biarkan saran lebih tinggi dari normal
            suggested_car = min(suggested_car, normal_values['carTravelKm'])
            suggested_shower = min(suggested_shower, normal_values['showerTimeMinutes'])
            suggested_electronic = min(suggested_electronic, normal_values['electronicTimeHours'])
            
            return {
                'suggestions': {
                    'carTravelKm': suggested_car,
                    'showerTimeMinutes': suggested_shower,
                    'electronicTimeHours': suggested_electronic
                },
                'membership_degrees': {
                    'carTravelKm': degree_car_high,
                    'showerTimeMinutes': degree_shower_long,
                    'electronicTimeHours': degree_electronic_much
                },
                'minimum_limits': {
                    'carTravelKm': min_car,
                    'showerTimeMinutes': min_shower,
                    'electronicTimeHours': min_electronic
                },
                'normal_values': normal_values
            }
        except Exception:
            return {
                'suggestions': {
                    'carTravelKm': car_km * 0.9,
                    'showerTimeMinutes': shower_min * 0.9,
                    'electronicTimeHours': electronic_hours * 0.9
                },
                'membership_degrees': {
                    'carTravelKm': 0,
                    'showerTimeMinutes': 0,
                    'electronicTimeHours': 0
                },
                'minimum_limits': {
                    'carTravelKm': car_km * 0.8,
                    'showerTimeMinutes': shower_min * 0.8,
                    'electronicTimeHours': electronic_hours * 0.8
                },
                'normal_values': normal_values
            }


def generate_improvement_suggestions(payload):
    """
    Generate improvement suggestions for other activities
    
    Args:
        payload (dict): User activity data
    
    Returns:
        list: List of improvement suggestions
    """
    suggestions = []
    
    # Negative activities (should be avoided)
    negative_activities = {
        'packagedFood': 'Avoid food packaged in plastic',
        'onlineShopping': 'Reduce online shopping/delivery',
        'wasteFood': 'Avoid wasting food',
        'airConditioningHeating': 'Minimize AC/heater usage'
    }
    
    # Positive activities (should be encouraged)
    positive_activities = {
        'noDriving': 'Use public transport/walk more',
        'plantMealThanMeat': 'Increase plant-based food intake',
        'useTumbler': 'Use a tumbler/reusable container',
        'saveEnergy': 'Turn off unnecessary devices/lights',
        'separateRecycleWaste': 'Sort and recycle your waste'
    }
    
    # Check negative activities
    for activity, suggestion in negative_activities.items():
        if payload.get(activity) is True:
            suggestions.append(suggestion)
    
    # Check positive activities (not doing them)
    for activity, suggestion in positive_activities.items():
        if payload.get(activity) is not True:
            suggestions.append(suggestion)
    
    return suggestions