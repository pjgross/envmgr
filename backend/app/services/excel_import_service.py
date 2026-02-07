"""
Excel import service for parsing and importing data from Excel templates.
"""
import pandas as pd
from typing import Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.user import User


class ExcelImportError(Exception):
    """Custom exception for Excel import errors."""
    pass


class ExcelImportService:
    """Service for importing data from Excel templates."""
    
    def __init__(self, db: AsyncSession, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id
        self.errors: List[Dict] = []
    
    async def validate_user_email(self, email: str) -> Optional[User]:
        """Validate that a user with the given email exists in the tenant."""
        result = await self.db.execute(
            select(User).where(
                User.email == email,
                User.tenant_id == self.tenant_id,
                User.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()
    
    def add_error(self, row: int, field: str, message: str):
        """Add a validation error."""
        self.errors.append({
            "row": row,
            "field": field,
            "message": message
        })
    
    async def parse_environment_template(self, file_path: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Parse environment import template.
        
        Returns:
            Tuple of (valid_records, errors)
        """
        self.errors = []
        valid_records = []
        
        try:
            # Read Excel file
            df = pd.read_excel(file_path, sheet_name='Environments')
            
            # Validate required columns
            required_columns = ['Name', 'Type', 'Status', 'Owner Email']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ExcelImportError(f"Missing required columns: {', '.join(missing_columns)}")
            
            # Process each row
            for idx, row in df.iterrows():
                row_num = idx + 2  # +2 because Excel is 1-indexed and has header row
                record = {}
                has_errors = False
                
                # Validate Name
                if pd.isna(row['Name']) or str(row['Name']).strip() == '':
                    self.add_error(row_num, 'Name', 'Name is required')
                    has_errors = True
                else:
                    record['name'] = str(row['Name']).strip()
                
                # Validate Type
                if pd.isna(row['Type']):
                    self.add_error(row_num, 'Type', 'Type is required')
                    has_errors = True
                elif str(row['Type']).strip() not in ['on-premise', 'cloud']:
                    self.add_error(row_num, 'Type', 'Type must be "on-premise" or "cloud"')
                    has_errors = True
                else:
                    record['type'] = str(row['Type']).strip()
                
                # Validate Status
                valid_statuses = ['active', 'inactive', 'maintenance', 'decommissioned']
                if pd.isna(row['Status']):
                    self.add_error(row_num, 'Status', 'Status is required')
                    has_errors = True
                elif str(row['Status']).strip() not in valid_statuses:
                    self.add_error(row_num, 'Status', f'Status must be one of: {", ".join(valid_statuses)}')
                    has_errors = True
                else:
                    record['status'] = str(row['Status']).strip()
                
                # Validate Owner Email
                if pd.isna(row['Owner Email']) or str(row['Owner Email']).strip() == '':
                    self.add_error(row_num, 'Owner Email', 'Owner Email is required')
                    has_errors = True
                else:
                    owner_email = str(row['Owner Email']).strip()
                    owner = await self.validate_user_email(owner_email)
                    if not owner:
                        self.add_error(row_num, 'Owner Email', f'User with email "{owner_email}" not found')
                        has_errors = True
                    else:
                        record['owner_id'] = owner.id
                
                # Optional fields
                record['tags'] = str(row.get('Tags', '')).strip() if not pd.isna(row.get('Tags')) else ''
                record['description'] = str(row.get('Description', '')).strip() if not pd.isna(row.get('Description')) else ''
                
                if not has_errors:
                    valid_records.append(record)
            
            return valid_records, self.errors
            
        except Exception as e:
            raise ExcelImportError(f"Error parsing Excel file: {str(e)}")
    
    async def parse_system_template(self, file_path: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Parse system import template.
        
        Returns:
            Tuple of (valid_records, errors)
        """
        self.errors = []
        valid_records = []
        
        try:
            # Read Excel file
            df = pd.read_excel(file_path, sheet_name='Systems')
            
            # Validate required columns
            required_columns = ['Name', 'Owner Email']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ExcelImportError(f"Missing required columns: {', '.join(missing_columns)}")
            
            # Process each row
            for idx, row in df.iterrows():
                row_num = idx + 2
                record = {}
                has_errors = False
                
                # Validate Name
                if pd.isna(row['Name']) or str(row['Name']).strip() == '':
                    self.add_error(row_num, 'Name', 'Name is required')
                    has_errors = True
                else:
                    record['name'] = str(row['Name']).strip()
                
                # Validate Owner Email
                if pd.isna(row['Owner Email']) or str(row['Owner Email']).strip() == '':
                    self.add_error(row_num, 'Owner Email', 'Owner Email is required')
                    has_errors = True
                else:
                    owner_email = str(row['Owner Email']).strip()
                    owner = await self.validate_user_email(owner_email)
                    if not owner:
                        self.add_error(row_num, 'Owner Email', f'User with email "{owner_email}" not found')
                        has_errors = True
                    else:
                        record['owner_id'] = owner.id
                
                # Optional fields
                record['description'] = str(row.get('Description', '')).strip() if not pd.isna(row.get('Description')) else ''
                record['github_repository_url'] = str(row.get('GitHub Repository URL', '')).strip() if not pd.isna(row.get('GitHub Repository URL')) else None
                
                if not has_errors:
                    valid_records.append(record)
            
            return valid_records, self.errors
            
        except Exception as e:
            raise ExcelImportError(f"Error parsing Excel file: {str(e)}")
    
    async def parse_project_template(self, file_path: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Parse project import template.
        
        Returns:
            Tuple of (valid_records, errors)
        """
        self.errors = []
        valid_records = []
        
        try:
            # Read Excel file
            df = pd.read_excel(file_path, sheet_name='Projects')
            
            # Validate required columns
            required_columns = ['Name', 'Team Members (comma-separated emails)']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ExcelImportError(f"Missing required columns: {', '.join(missing_columns)}")
            
            # Process each row
            for idx, row in df.iterrows():
                row_num = idx + 2
                record = {}
                has_errors = False
                
                # Validate Name
                if pd.isna(row['Name']) or str(row['Name']).strip() == '':
                    self.add_error(row_num, 'Name', 'Name is required')
                    has_errors = True
                else:
                    record['name'] = str(row['Name']).strip()
                
                # Validate Team Members
                team_members_col = 'Team Members (comma-separated emails)'
                if pd.isna(row[team_members_col]) or str(row[team_members_col]).strip() == '':
                    self.add_error(row_num, 'Team Members', 'At least one team member email is required')
                    has_errors = True
                else:
                    emails = [e.strip() for e in str(row[team_members_col]).split(',')]
                    team_member_ids = []
                    
                    for email in emails:
                        if email:
                            user = await self.validate_user_email(email)
                            if not user:
                                self.add_error(row_num, 'Team Members', f'User with email "{email}" not found')
                                has_errors = True
                            else:
                                team_member_ids.append(user.id)
                    
                    if team_member_ids:
                        record['team_member_ids'] = team_member_ids
                
                # Optional fields
                record['description'] = str(row.get('Description', '')).strip() if not pd.isna(row.get('Description')) else ''
                
                if not has_errors:
                    valid_records.append(record)
            
            return valid_records, self.errors
            
        except Exception as e:
            raise ExcelImportError(f"Error parsing Excel file: {str(e)}")
