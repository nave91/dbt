
import dbt.utils
import dbt.flags


class BaseMaterializer(object):
    def __init__(self, adapter, node, existing, non_destructive, full_refresh):
        self.adapter = adapter
        self.node = node
        self.existing = existing

        self.non_destructive = non_destructive
        self.full_refresh = full_refresh

    def tmp_name(self):
        node_name = self.node.get('name')
        return '{}__dbt_tmp'.format(node_name)

    def final_name(self):
        return self.node.get('name')

    def existing_tmp_type(self):
        return self.existing.get(self.tmp_name())

    def existing_final_type(self):
        return self.existing.get(self.final_name())

    def __drop_tmp_if_any(self, profile): 
        existing_type = self.existing_tmp_type()
        if existing_type is not None:
            self.drop(profile, self.tmp_name(), existing_type)

    def before_materialize(self, profile):
        pass

    def materialize(self, profile):
        # Make room for new relations. Temp tables can always be dropped
        # They will only exist here if a previous run failed btwn transactions
        self.__drop_tmp_if_any(profile)

        self.before_materialize(profile)
        result = self.do_materialize(profile)
        self.after_materialize(profile)
        return result

    def do_materialize(self, profile):
        return self.adapter.execute_model(profile, self.node)

    def after_materialize(self, profile):
        pass

    def drop(self, profile, relation_name, relation_type):
        return self.adapter.drop(profile, relation_name, relation_type,
                                 self.node.get('name'))

    def truncate(self, profile, relation_name):
        return self.adapter.truncate(profile, relation_name,
                                     self.node.get('name'))

    def rename(self, profile, from_name, to_name):
        return self.adapter.rename(profile, from_name, to_name,
                                   self.node.get('name'))

class TableMaterializer(BaseMaterializer):

    def before_materialize(self, profile):
        existing_type = self.existing_final_type()

        if self.non_destructive and existing_type == 'table':
            self.truncate(profile, self.final_name())

        elif self.non_destructive and existing_type == 'view':
            self.drop(profile, self.final_name(), existing_type)

    def after_materialize(self, profile):
        if self.non_destructive:
            return

        self.drop(profile, self.final_name(), 'table')
        self.rename(profile, self.tmp_name(), self.final_name())

class ViewMaterializer(BaseMaterializer):

    def do_materialize(self, profile):
        existing_type = self.existing_final_type()

        if self.non_destructive and existing_type == 'view':
            return 'PASS'
        else:
            return super(ViewMaterializer, self).do_materialize(profile)

    def after_materialize(self, profile):
        existing_type = self.existing_final_type()

        if self.non_destructive and existing_type == 'view':
            return

        self.drop(profile, self.final_name(), existing_type)
        self.rename(profile, self.tmp_name(), self.final_name())

class IncrementalMaterializer(BaseMaterializer):

    def before_materialize(self, profile):
        existing_type = self.existing_final_type()
        exists_as_table = (existing_type == 'table')

        if self.non_destructive and self.full_refresh and exists_as_table:
            self.truncate(profile, self.final_name())
        elif self.full_refresh or not exists_as_table:
            self.drop(profile, self.final_name(), existing_type)

    def after_materialize(self, profile):
        pass


def get_materializer(adapter, node, existing):
    materializer_classes = {
        "table": TableMaterializer,
        "view": ViewMaterializer,
        "incremental": IncrementalMaterializer,
    }

    materialized = dbt.utils.get_materialization(node)
    klass = materializer_classes.get(materialized)

    if klass is None:
        raise RuntimeError("Base materialization: {}".format(materialized))
    else:
        return klass(adapter, node, existing, dbt.flags.NON_DESTRUCTIVE,
                     dbt.flags.FULL_REFRESH)

