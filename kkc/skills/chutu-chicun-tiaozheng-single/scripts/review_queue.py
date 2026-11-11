"""Batch gallery or explicit individual review; only human-confirmed delivery."""
import copy
import json
import re
import shutil
from pathlib import Path

from task_spec import digest, load_jobs
from delivery_spec import normalize_delivery
from user_profile import effective_job, file_hash, identifier, now, read_json, write_json
from validate_candidate import assert_render, preview_pair, source_preview
from PIL import Image, ImageOps


class ReviewQueue:
    def __init__(self, store, engine):
        self.store, self.engine = store, engine

    def path(self, review_id):
        if not re.fullmatch(r'r-[A-Za-z0-9-]+', review_id):
            raise ValueError('非法逐张审核ID')
        return self.store.root / 'reviews' / review_id / 'review.json'

    def load(self, review_id):
        self.store.owned()
        record = read_json(self.path(review_id))
        current, _, _ = self.store.active()
        if current != record['revision']:
            raise ValueError('个人正式版本已变化，请以新版本重新逐张预览')
        for item in record['items']:
            if item['status'] == 'confirmed':
                self._check_preview(item)
        return record

    def save(self, record):
        write_json(self.path(record['id']), record)
        return record

    @staticmethod
    def _invalidate_overview(record):
        if record.get('batch_preview'):
            record.setdefault('batch_preview_history',[]).append(record.pop('batch_preview'))
        if record.get('batch_confirmation'):
            record.setdefault('batch_confirmation_history',[]).append(record.pop('batch_confirmation'))

    @staticmethod
    def _invalidate_item(item):
        if item.get('status')=='confirmed':
            item.setdefault('confirmation_history',[]).append({key:item[key] for key in
                ('preview','digest','confirmation','confirmed_at','confirmation_kind','style_authorization_id') if key in item})
        item['status']='pending'
        for key in ('preview','preview_sha256','digest','framing','backend_risk','confirmation','confirmed_at',
                    'confirmation_kind','style_authorization_id','preview_kind','preview_only','preview_transparency'):
            item.pop(key,None)

    @staticmethod
    def _layout(record):
        groups={};used=set()
        for index,item in enumerate(record['items'],1):
            delivery=item['job'].get('_delivery',{})
            raw=str(delivery.get('size',item['job']['size']))
            match=re.fullmatch(r'\s*(\d+)\s*[xX×*]\s*(\d+)\s*',raw)
            if not match:raise ValueError('预览分组尺寸无效')
            size='x'.join(str(int(value)) for value in match.groups())
            number=delivery.get('index',index)
            if type(number) is not int or number<1 or (size,number) in used:raise ValueError('预览来源序号无效或重复')
            used.add((size,number))
            groups.setdefault(size,{'size':size,'items':[],'contact_sheets':[]})['items'].append({
                'index':index,'number':number,'preview':item.get('preview'),'digest':item.get('digest'),
                'preview_sha256':item.get('preview_sha256'),'preview_kind':item.get('preview_kind')})
        for group in groups.values():group['items'].sort(key=lambda row:row['number'])
        return list(groups.values())

    @staticmethod
    def _sources_unchanged(record):
        for item in record['items']:
            if not Path(item['job']['input']).is_file() or file_hash(item['job']['input'])!=item['source_sha256']:
                raise ValueError('原图已变化，请重新建立审核队列')

    def _preflight(self,record,*,all_items=False):
        from backend_policy import BackendChoiceRequired
        self._sources_unchanged(record);risks=[]
        for index,item in enumerate(record['items'],1):
            if item['status']=='confirmed' and not all_items:continue
            try:self.engine.processing_plan(item['job'])
            except BackendChoiceRequired as error:
                delivery=item['job'].get('_delivery',{})
                risks.append({'index':index,'number':delivery.get('index',index),
                              'size':delivery.get('size',item['job']['size']),'risk':error.report})
        return risks

    def _gallery_root(self,record):
        policy=record.get('delivery_policy')
        root=Path(policy['out_dir']).resolve() if policy else self.path(record['id']).parent.resolve()
        parent=root/'预览'/record['id'] if policy else root/'batch-previews'
        if not parent.resolve().is_relative_to(root):raise ValueError('预览目录越过本批输出根目录')
        return parent

    def _verify_batch_preview(self,record,expected_digest=None):
        overview=record.get('batch_preview')
        if not overview:raise ValueError('整批总览已失效或尚未生成，请先review-preview-all')
        if expected_digest is not None and overview['digest']!=expected_digest:raise ValueError('整批总览确认摘要已过时')
        manifest_path=Path(overview['manifest'])
        if not manifest_path.is_file() or file_hash(manifest_path)!=overview['manifest_sha256']:
            raise ValueError('整批总览manifest缺失或变化')
        manifest=read_json(manifest_path)
        if digest(manifest)!=overview['digest'] or manifest.get('review_id')!=record['id'] or manifest.get('revision')!=record['revision']:
            raise ValueError('整批总览manifest摘要或版本不符')
        self._sources_unchanged(record)
        bindings=[]
        for index,item in enumerate(record['items'],1):
            if item['status'] not in ('previewed','confirmed'):raise ValueError('仍有候选缺少有效预览，不能集中确认')
            self._check_preview(item)
            if item.get('preview_kind')!='target' or item.get('preview_only') is not True:
                raise ValueError('整批必须使用目标尺寸结果预览，不能复用旧原图对照')
            target=tuple(map(int,str(item['job']['size']).lower().replace('×','x').replace('*','x').replace(' ','').split('x')))
            with Image.open(item['preview']) as opened:
                if opened.size!=target:raise ValueError('整批目标预览本身尺寸不符')
            bindings.append({'index':index,'digest':item['digest'],'source_sha256':item['source_sha256'],
                             'job_digest':digest(item['job']),'revision':item['revision']})
        if manifest.get('items_binding')!=bindings or manifest.get('groups')!=overview['groups']:
            raise ValueError('整批总览候选绑定不完整或过时')
        groups=self._layout(record)
        if len(groups)!=len(overview['groups']):raise ValueError('整批总览尺寸组缺失')
        required=set()
        for expected,actual in zip(groups,overview['groups']):
            if expected['size']!=actual.get('size') or expected['items']!=actual.get('items') or not actual.get('contact_sheets'):
                raise ValueError('整批总览候选或总览页缺失')
            if len(actual['contact_sheets'])!=(len(actual['items'])+19)//20:
                raise ValueError('整批总览分页数量不完整')
            required.update(row['preview'] for row in actual['items']);required.update(actual['contact_sheets'])
        if set(manifest.get('files',{}))!=required:raise ValueError('整批总览文件清单不完整')
        generation=manifest_path.parent.resolve()
        if generation.parent!=self._gallery_root(record).resolve():raise ValueError('整批总览不在本批预览目录')
        for path,sha256 in manifest['files'].items():
            file=Path(path)
            if not file.resolve().is_relative_to(generation) or not file.is_file() or file_hash(file)!=sha256:
                raise ValueError('整批预览/总览文件缺失或被篡改')
        if {str(path.resolve()) for path in generation.rglob('*') if path.is_file()}!={str(Path(path).resolve()) for path in required}|{str(manifest_path.resolve())}:
            raise ValueError('整批总览目录出现未绑定文件或缺项')
        return overview

    def preview_all(self,review_id):
        """Preflight the entire pending set before creating any target pixels."""
        raise ValueError('逐张版禁止整批预览，请使用review-next逐张预览确认')
        from batch_preview import contact_sheets,save_target_preview
        with self.store.lock():
            record=self.load(review_id)
            if record.get('execution_batch'):raise ValueError('本批已开始交付，不能重建预览')
            record['review_mode']='batch';groups=self._layout(record);risks=self._preflight(record)
            if risks:
                self._invalidate_overview(record)
                for row in risks:
                    item=record['items'][row['index']-1]
                    item.update(status='awaiting_backend_choice',backend_risk=row['risk'])
                self.save(record)
                for group in groups:group['risks']=[row for row in risks if row['size']==group['size']]
                return {'review_id':review_id,'ready':False,'requires_backend_choice':True,'risks':risks,'groups':groups,
                        'next':'集中说明各尺寸风险并人工选择Python或PS，再review-preview-all；本轮未生成任何新目标预览'}
            if record.get('batch_preview'):
                try:
                    overview=self._verify_batch_preview(record)
                except (ValueError,OSError,KeyError):pass
                else:
                    self.save(record)
                    return {'review_id':review_id,'ready':self.current(record) is None,'requires_backend_choice':False,
                            'risks':[],'groups':overview['groups'],'batch_digest':overview['digest'],
                            'manifest':overview['manifest'],'reused':True,'preview_only':True,'next':'展示全部尺寸总览后review-confirm-all'}
            self._invalidate_overview(record);valid_rows={}
            for index,item in enumerate(record['items'],1):
                valid=False
                if item.get('preview_kind')=='target' and item.get('preview_only') is True:
                    try:
                        self._check_preview(item)
                        target=tuple(map(int,str(item['job']['size']).lower().replace('×','x').replace('*','x').replace(' ','').split('x')))
                        with Image.open(item['preview']) as opened:valid=opened.size==target
                    except (ValueError,OSError,KeyError):pass
                valid_rows[index]=valid
                if not valid:self._invalidate_item(item)
            # A failed generation must leave old comparison approvals invalid.
            self.save(record)
            parent=self._gallery_root(record);parent.mkdir(parents=True,exist_ok=True)
            generation=parent/identifier('generation-');generation.mkdir()
            for group in groups:
                folder=generation/group['size'];folder.mkdir()
                for row in group['items']:
                    item=record['items'][row['index']-1];preview=folder/f'{row["number"]}.jpg'
                    if valid_rows[row['index']]:
                        shutil.copyfile(item['preview'],preview)
                    else:
                        src,output,plan,_=self.engine._render(item['job']);assert_render(output,plan,item['job'])
                        item['preview_transparency']=save_target_preview(output,preview,item['job'])
                        item.update(status='previewed',framing=plan)
                    if file_hash(item['job']['input'])!=item['source_sha256']:raise ValueError('预览期间原图变化，整批总览不发布')
                    item.update(preview=str(preview),preview_sha256=file_hash(preview),preview_kind='target',preview_only=True)
                    item['digest']=digest({'job':item['job'],'source':item['source_sha256'],
                                           'preview':item['preview_sha256'],'revision':item['revision']})
                    item.pop('backend_risk',None)
                    item['attempts'].append({'preview':str(preview),'digest':item['digest'],'mode':'batch',
                                             'preview_kind':'target','preview_only':True})
                    row.update(preview=item['preview'],digest=item['digest'],preview_sha256=item['preview_sha256'],preview_kind='target')
                group['contact_sheets']=contact_sheets(group['items'],folder,group['size'])
            self._sources_unchanged(record)
            files={path:file_hash(path) for group in groups for path in
                   [*[row['preview'] for row in group['items']],*group['contact_sheets']]}
            manifest={'schema':1,'review_id':review_id,'revision':record['revision'],'created_at':now(),'groups':groups,'files':files,
                      'preview_only':True,'preview_kind':'target',
                      'items_binding':[{'index':index,'digest':item['digest'],'source_sha256':item['source_sha256'],
                                        'job_digest':digest(item['job']),'revision':item['revision']}
                                       for index,item in enumerate(record['items'],1)]}
            manifest_path=generation/'manifest.json';write_json(manifest_path,manifest)
            record['batch_preview']={'digest':digest(manifest),'groups':groups,'manifest':str(manifest_path),
                                     'manifest_sha256':file_hash(manifest_path),'generation':str(generation),'created_at':manifest['created_at']}
            self._verify_batch_preview(record);self.save(record)
            return {'review_id':review_id,'ready':False,'requires_backend_choice':False,'risks':[],
                    'groups':groups,'batch_digest':record['batch_preview']['digest'],'manifest':str(manifest_path),
                    'preview_only':True,'next':'展示所有尺寸的全部总览与候选，真实集中确认后review-confirm-all'}

    def confirm_all(self,review_id,expected_digest,confirmation):
        raise ValueError('逐张版禁止整批确认，请使用review-confirm逐张真实确认')
        with self.store.lock():
            if not isinstance(confirmation,str) or not confirmation.strip():raise ValueError('集中确认必须记录用户真实原文')
            if not isinstance(expected_digest,str) or not expected_digest:raise ValueError('集中确认必须提供当前整批总览摘要')
            record=self.load(review_id)
            if record.get('execution_batch'):raise ValueError('本批已开始交付，不能重新集中确认')
            if record.get('batch_confirmation'):raise ValueError('本批已集中确认，不能重复批准')
            overview=self._verify_batch_preview(record,expected_digest)
            if self._preflight(record,all_items=True):raise ValueError('仍有放大风险或结构问题未选择，不能集中确认')
            self._verify_batch_preview(record,expected_digest)
            timestamp=now();record['review_mode']='batch'
            record['batch_confirmation']={'kind':'human_batch_preview_confirmation','text':confirmation,
                'digest':expected_digest,'confirmed_at':timestamp,'source':'human_message',
                'indices':list(range(1,len(record['items'])+1)),'manifest':overview['manifest']}
            for item in record['items']:
                item.update(status='confirmed',confirmation=confirmation,confirmed_at=timestamp,
                            confirmation_kind='human_batch_preview_confirmation')
            self.save(record)
            write_json(self.path(review_id).parent/'approved-spec.json',
                       {'product_focus':record['product_focus'],'jobs':[item['job'] for item in record['items']]})
            return {'review_id':review_id,'ready':True,'confirmed':len(record['items']),'batch_digest':expected_digest,
                    'next':'batch --review '+review_id}

    def adjust_item(self,review_id,index,patch):
        with self.store.lock():
            record=self.load(review_id)
            if record.get('execution_batch'):raise ValueError('本批已开始交付，调整需新建任务')
            if type(index) is not int or not 1<=index<=len(record['items']):raise ValueError('候选序号无效')
            allowed={'fit','bg','focus','position','offset','zoom','crop_box','subject_box','protect_box','subject_fill',
                     'allow_padding','allow_stretch','on_conflict'}
            if not isinstance(patch,dict) or not patch or set(patch)-allowed:raise ValueError('只能调整候选构图参数，尺寸/命名/路径/格式等规格已冻结')
            item=record['items'][index-1];job=copy.deepcopy(item['job'])
            for key,value in patch.items():
                if value is None:job.pop(key,None)
                else:job[key]=value
            self.engine.resolve_job(job)
            self._sources_unchanged(record)
            # Keep an outdated choice binding: resolve_backend must require a
            # new human selection even if the revised crop no longer upscales.
            if job.get('_backend_choice'):
                analysis=self.engine.processing_plan(job,require_choice=False)
                if job['_backend_choice']['basis_digest']!=analysis['processing']['risk']['basis_digest']:
                    item.setdefault('backend_choice_invalidations',[]).append({'at':now(),'reason':'geometry_changed'})
            item['job']=job;self._invalidate_item(item);self._invalidate_overview(record)
            record['review_mode']='batch';self.save(record)
            return {'review_id':review_id,'index':index,'requires_preview_all':True,'ready':False,
                    'next':'review-preview-all；只失效指定候选，未自动渲染其他项'}

    @staticmethod
    def _check_preview(item):
        if not item.get('preview') or not Path(item['preview']).is_file() or file_hash(item['preview']) != item['preview_sha256']:
            raise ValueError('已确认预览缺失或变化，请重新逐张审核')
        expected = digest({'job': item['job'], 'source': item['source_sha256'],
                           'preview': item['preview_sha256'], 'revision': item['revision']})
        if item.get('digest') != expected:
            raise ValueError('图片参数与预览摘要不一致，请重新预览')

    def start(self, spec_path):
        with self.store.lock():
            revision, _, settings = self.store.active()
            delivery = normalize_delivery(spec_path)
            jobs = delivery['jobs'] if delivery else load_jobs(spec_path)
            review_id = identifier('r-')
            items = []
            for job in jobs:
                job = effective_job(settings, job)
                job['_backend_review'] = review_id
                job['input'] = str(Path(job['input']).expanduser().resolve())
                job['out_dir'] = str(Path(job.get('out_dir', '.')).expanduser().resolve())
                items.append({'job': job, 'source_sha256': file_hash(job['input']),
                              'revision': revision, 'status': 'pending', 'attempts': []})
            record = {'schema': 1, 'id': review_id, 'revision': revision, 'created_at': now(),
                      'items': items, 'execution_batch': None,'review_mode':'individual',
                      'product_focus': read_json(spec_path).get('product_focus', {})}
            if delivery:
                record['delivery_policy']=delivery['policy']
            self.save(record)
            return {'review_id': review_id, 'total': len(items), 'next': 'review-next；统一预检风险后仅预览当前张，确认后才进入下一张'}

    @staticmethod
    def current(record):
        return next((i for i, item in enumerate(record['items']) if item['status'] != 'confirmed'), None)

    def next(self, review_id):
        with self.store.lock():
            record = self.load(review_id)
            index = self.current(record)
            if index is None:
                if record.get('review_mode')=='batch':self.ready(review_id)
                return {'review_id': review_id, 'ready': True, 'confirmed': len(record['items']),
                        'next': 'batch --review ' + review_id}
            record['review_mode']='individual'
            risks=self._preflight(record)
            if risks:
                for row in risks:
                    pending=record['items'][row['index']-1]
                    pending.update(status='awaiting_backend_choice',backend_risk=row['risk'])
                self.save(record)
                return {'review_id':review_id,'index':index+1,'total':len(record['items']),
                        'ready':False,'requires_backend_choice':True,'preview':None,
                        'risk':risks[0]['risk'],'risks':risks,'options':risks[0]['risk']['options'],
                        'next':'先集中说明放大/结构风险并选择PS或Python，再review-next当前张'}
            self.save(record)
            item = record['items'][index]
            if file_hash(item['job']['input']) != item['source_sha256']:
                raise ValueError('当前原图变化，请重新建立逐张预览队列')
            if item['status'] != 'previewed' or item.get('preview_kind')=='target':
                from backend_policy import BackendChoiceRequired
                try:
                    src, output, plan, _ = self.engine._render(item['job'])
                except BackendChoiceRequired as choice:
                    item.update(status='awaiting_backend_choice',backend_risk=choice.report)
                    self.save(record)
                    return {'review_id':review_id,'index':index+1,'total':len(record['items']),
                            'ready':False,'requires_backend_choice':True,'preview':None,
                            'risk':choice.report,'options':choice.report['options'],
                            'next':('Python不支持当前源结构，请人工选择PS或提供兼容副本；不自动切换或生成目标预览'
                                    if choice.report.get('python_supported') is False else
                                    '说明源尺寸、实际取景、目标及倍率，请人工选择Python或PS；未选不生成目标尺寸预览')}
                assert_render(output, plan, item['job'])
                self._invalidate_overview(record)
                preview = self.path(review_id).parent / f'{index+1:04d}-{identifier("preview-")}.jpg'
                with source_preview(src,item['job'].get('source_layers')) as original:
                    delivery=item['job'].get('_delivery')
                    title=(f'第{delivery["index"]}/{delivery["source_count"]}张 · {delivery["size"]}：{src.name}'
                           if delivery else f'第{index+1}/{len(record["items"])}张：{src.name}')
                    preview_pair(original, output, preview, title)
                if file_hash(src) != item['source_sha256']:
                    raise ValueError('预览期间原图变化，请重新建立队列')
                item.update(status='previewed', preview=str(preview), preview_sha256=file_hash(preview), framing=plan,
                            preview_kind='comparison',preview_only=True)
                item['digest'] = digest({'job': item['job'], 'source': item['source_sha256'],
                                         'preview': item['preview_sha256'], 'revision': item['revision']})
                item['attempts'].append({'preview': str(preview), 'digest': item['digest']})
                self.save(record)
            self._check_preview(item)
            return {'review_id': review_id, 'index': index+1, 'total': len(record['items']),
                    'preview': item['preview'], 'digest': item['digest'], 'job': item['job'],
                    'product_focus': record['product_focus'],
                    'delivery': item['job'].get('_delivery'),
                    'ready': False, 'next': '展示当前图片；要求修改则review-adjust，真实确认后review-confirm'}

    def select_backend(self,review_id,backend,confirmation,to_index=None,indices=None):
        from backend_policy import make_choice
        with self.store.lock():
            record=self.load(review_id)
            if record.get('execution_batch'):raise ValueError('队列已经开始交付，切换处理方式需新建任务')
            index=self.current(record)
            if indices is not None:
                if to_index is not None or not isinstance(indices,list) or not indices or any(type(value) is not int or not 1<=value<=len(record['items']) for value in indices) or len(set(indices))!=len(indices):
                    raise ValueError('indices必须为有效且不重复的候选序号列表，不能同时指定to_index')
                positions=[value-1 for value in indices]
            else:
                if index is None:raise ValueError('本批已完成审核，请新建任务再修改处理方式')
                end=index+1 if to_index is None else to_index
                if type(end) is not int or not index+1<=end<=len(record['items']):raise ValueError('后端选择范围无效')
                positions=list(range(index,end))
            choices=[]
            for position in positions:
                item=record['items'][position]
                if file_hash(item['job']['input'])!=item['source_sha256']:raise ValueError('原图已变化，不能复用旧队列')
                analysis=self.engine.processing_plan(item['job'],require_choice=False)
                choice=make_choice(item['job'],analysis['plan'],backend,confirmation)
                choices.append((position,choice))
            # Stage all bindings before mutating the review, so a failed later
            # source cannot leave a partially authorized range.
            for position,choice in choices:
                item=record['items'][position]
                item['job']['_backend_choice']=choice
                self._invalidate_item(item)
                item.setdefault('backend_choices',[]).append({'choice':choice,'selected_at':now(),
                    'source':'human_message','range_start':min(positions)+1,'range_end':max(positions)+1,
                    'indices':[position+1 for position in positions]})
            self._invalidate_overview(record)
            self.save(record)
            return {'review_id':review_id,'backend':backend,'from_candidate':min(positions)+1,'to_candidate':max(positions)+1,
                    'indices':[position+1 for position in positions],'choices':[choice for _,choice in choices],
                    'next':'review-preview-all；重新预检整批风险，不自动批准画面' if record.get('review_mode')=='batch'
                           else 'review-next；仅处理当前候选，不自动批准画面'}

    def adjust(self, review_id, patch):
        with self.store.lock():
            record = self.load(review_id)
            if record.get('execution_batch'):
                raise ValueError('队列已经开始出图，修改需建立新队列和新输出目录')
            index = self.current(record)
            if index is None:
                raise ValueError('全批已确认，需要修改时请建立新队列')
            if not isinstance(patch, dict) or 'input' in patch:
                raise ValueError('调整必须是参数对象；替换原图请建立新队列')
            allowed = {'size','name','out_dir','format','fit','bg','psd','save_recipe','preset','focus',
                       'position','offset','zoom','crop_box','subject_box','protect_box','subject_fill',
                       'allow_padding','allow_stretch','on_conflict'}
            if set(patch) - allowed:
                raise ValueError('调整包含不支持的参数')
            item = record['items'][index]
            if item['job'].get('_delivery') and set(patch)&{'size','name','out_dir','format','psd','max_bytes'}:
                raise ValueError('数据包交付规格和人工命名已绑定，修改交付方案请新建任务；此处只调整构图')
            # null removes an optional parameter, making focus/crop refinements reversible.
            for key, value in patch.items():
                if value is None:
                    item['job'].pop(key, None)
                else:
                    item['job'][key] = value
            self.engine.resolve_job(item['job'])
            item['status'] = 'pending'
            for key in ('preview', 'preview_sha256', 'digest', 'framing'):
                item.pop(key, None)
            self._invalidate_overview(record);record['review_mode']='individual'
            self.save(record)
        return self.next(review_id)

    def confirm(self, review_id, expected_digest, confirmation):
        with self.store.lock():
            if not confirmation.strip():
                raise ValueError('必须记录用户对当前图片的真实确认原文')
            record = self.load(review_id)
            record['review_mode']='individual'
            index = self.current(record)
            if index is None:
                raise ValueError('本批已经全部确认')
            item = record['items'][index]
            if item['status'] != 'previewed' or item.get('digest') != expected_digest:
                raise ValueError('当前图片未预览或确认摘要已过时')
            if file_hash(item['job']['input']) != item['source_sha256']:
                raise ValueError('当前原图已变化，不能批准旧预览')
            self._check_preview(item)
            authorizations=record.get('style_authorizations',[])
            matching=[a for a in authorizations if a['text']==confirmation]
            authorization=next((a for a in reversed(matching) if a['from_candidate']<=index+1<=a['to_candidate']),None)
            if matching and authorization is None:
                raise ValueError('这条风格授权不覆盖当前候选，不能扩展到未授权图片或尺寸')
            if authorization:
                reference=record['items'][authorization['reference_candidate']-1]
                self._check_preview(reference)
                if reference['digest']!=authorization['reference_digest'] or file_hash(reference['job']['input'])!=reference['source_sha256']:
                    raise ValueError('风格参考预览或源文件已变化，本批风格授权失效')
                item.update(confirmation_kind='human_batch_style_delegation',style_authorization_id=authorization['id'])
            else:
                item['confirmation_kind']='human_current_preview_confirmation'
            item.update(status='confirmed', confirmation=confirmation, confirmed_at=now())
            self.save(record)
            ready = self.current(record) is None
            if ready:
                write_json(self.path(review_id).parent / 'approved-spec.json',
                           {'product_focus': record['product_focus'], 'jobs': [i['job'] for i in record['items']]})
            return {'review_id': review_id, 'confirmed_index': index+1, 'ready': ready,
                    'next': 'batch --review ' + review_id if ready else 'review-next；现在才开始下一张的预览调整'}

    def authorize_style(self,review_id,confirmation,reference_index,from_index=None,to_index=None):
        raise ValueError('逐张版禁止风格授权跳过逐张确认')
        with self.store.lock():
            if not isinstance(confirmation,str) or not confirmation.strip():raise ValueError('风格授权必须记录真实用户原文')
            record=self.load(review_id);current=self.current(record)
            record['review_mode']='legacy_individual'
            if current is None or record.get('execution_batch'):raise ValueError('本批已完成审核或开始生成，不能追加风格授权')
            if type(reference_index) is not int or not 1<=reference_index<=len(record['items']):raise ValueError('风格参考候选序号无效')
            reference=record['items'][reference_index-1]
            if reference['status'] not in ('previewed','confirmed'):raise ValueError('风格参考必须已经生成并展示预览')
            self._check_preview(reference)
            start=current+1 if from_index is None else from_index
            end=len(record['items']) if to_index is None else to_index
            if type(start) is not int or type(end) is not int or not current+1<=start<=end<=len(record['items']):
                raise ValueError('风格授权只能覆盖本批尚未确认的有效候选范围')
            authorization={'id':identifier('a-'),'text':confirmation,'source':'human_message','created_at':now(),
                           'from_candidate':start,'to_candidate':end,'reference_candidate':reference_index,
                           'reference_digest':reference['digest'],'reference_preview':reference['preview'],
                           'scope':[{'candidate':i+1,'input':record['items'][i]['job']['input'],'size':record['items'][i]['job']['size']}
                                    for i in range(start-1,end)],
                           'per_image_human_preview_required':False,'scope_note':'仅本批所列图片和尺寸，不改变长期偏好'}
            record.setdefault('style_authorizations',[]).append(authorization);self.save(record)
            return {'review_id':review_id,'authorization_id':authorization['id'],'from_candidate':start,'to_candidate':end,
                    'next':'逐图检查当前及后续候选；仅按该真实授权范围执行，不伪造逐张人类看图'}

    def ready(self, review_id):
        record = self.load(review_id)
        if self.current(record) is not None:
            raise ValueError('还有图片未逐张预览确认，不能开始正式出图')
        for item in record['items']:
            if file_hash(item['job']['input']) != item['source_sha256']:
                raise ValueError('原图与已确认预览不一致，请重新建立逐张预览队列')
        if record.get('review_mode')!='individual' or record.get('style_authorizations'):
            raise ValueError('逐张版只接受真实逐张预览确认')
        if any(item.get('confirmation_kind')!='human_current_preview_confirmation' for item in record['items']):
            raise ValueError('每张候选均须真实确认当前预览，不能沿用风格或整批确认')
        if record.get('review_mode')=='batch':
            confirmation=record.get('batch_confirmation')
            if not confirmation or confirmation.get('kind')!='human_batch_preview_confirmation':
                raise ValueError('整批预览缺少真实集中确认，不能开始正式出图')
            self._verify_batch_preview(record,confirmation['digest'])
        return record

    def bind_batch(self, review_id, batch_id):
        with self.store.lock():
            record = self.ready(review_id)
            if record['execution_batch'] and record['execution_batch'] != batch_id:
                raise ValueError('逐张确认队列已经绑定其他批次')
            record['execution_batch'] = batch_id
            self.save(record)
